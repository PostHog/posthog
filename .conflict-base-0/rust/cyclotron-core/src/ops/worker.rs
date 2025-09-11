use chrono::{DateTime, Utc};
use sqlx::{postgres::PgArguments, query::Query, Encode, QueryBuilder, Type};
use uuid::Uuid;

use crate::{
    error::QueueError,
    ops::compress::decompress_vm_state,
    types::{Bytes, Job, JobState, JobUpdate},
};

use super::{compress::compress_vm_state, meta::throw_if_no_rows};

// Dequeue the next job batch from the queue, skipping VM state since it can be large
pub async fn dequeue_jobs<'c, E>(
    executor: E,
    queue: &str,
    max: usize,
) -> Result<Vec<Job>, QueueError>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    // Transient lock id. This could be a worker ID, or something, but for now it's totally random (per-batch)
    let lock_id = Uuid::now_v7();
    Ok(sqlx::query_as!(
        Job,
        r#"
WITH available AS (
    SELECT
        id,
        state
    FROM cyclotron_jobs
    WHERE
        state = 'available'::JobState
        AND queue_name = $1
        AND scheduled <= NOW()
    ORDER BY
        priority ASC,
        scheduled ASC
    LIMIT $2
    FOR UPDATE SKIP LOCKED
)
UPDATE cyclotron_jobs
SET
    state = 'running'::JobState,
    lock_id = $3,
    last_heartbeat = NOW(),
    last_transition = NOW(),
    transition_count = transition_count + 1
FROM available
WHERE
    cyclotron_jobs.id = available.id
RETURNING
    cyclotron_jobs.id,
    team_id,
    available.state as "state: JobState",
    queue_name,
    priority,
    function_id,
    created,
    last_transition,
    scheduled,
    transition_count,
    NULL::bytea as vm_state,
    metadata,
    parameters,
    blob,
    lock_id,
    last_heartbeat,
    janitor_touch_count
    "#,
        queue,
        max as i64,
        lock_id
    )
    .fetch_all(executor)
    .await?)
}

// Dequeue a batch of jobs, with their VM state.
pub async fn dequeue_with_vm_state<'c, E>(
    executor: E,
    queue: &str,
    max: usize,
) -> Result<Vec<Job>, QueueError>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    let lock_id = Uuid::now_v7();
    let result = sqlx::query_as!(
        Job,
        r#"
WITH available AS (
    SELECT
        id,
        state
    FROM cyclotron_jobs
    WHERE
        state = 'available'::JobState
        AND queue_name = $1
        AND scheduled <= NOW()
    ORDER BY
        priority ASC,
        scheduled ASC
    LIMIT $2
    FOR UPDATE SKIP LOCKED
)
UPDATE cyclotron_jobs
SET
    state = 'running'::JobState,
    lock_id = $3,
    last_heartbeat = NOW(),
    last_transition = NOW(),
    transition_count = transition_count + 1
FROM available
WHERE
    cyclotron_jobs.id = available.id
RETURNING
    cyclotron_jobs.id,
    team_id,
    available.state as "state: JobState",
    queue_name,
    priority,
    function_id,
    created,
    last_transition,
    scheduled,
    transition_count,
    vm_state,
    metadata,
    parameters,
    blob,
    lock_id,
    last_heartbeat,
    janitor_touch_count
    "#,
        queue,
        max as i64,
        lock_id
    )
    .fetch_all(executor)
    .await?;

    let mut out: Vec<Job> = Vec::with_capacity(result.len());
    for mut job in result {
        job.vm_state = decompress_vm_state(job.vm_state);
        out.push(job);
    }

    Ok(out)
}

pub async fn get_vm_state<'c, E>(
    executor: E,
    job_id: Uuid,
    lock_id: Uuid,
) -> Result<Option<Bytes>, QueueError>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    struct VMState {
        vm_state: Option<Bytes>,
    }

    let res = sqlx::query_as!(
        VMState,
        "SELECT vm_state FROM cyclotron_jobs WHERE id = $1 AND lock_id = $2",
        job_id,
        lock_id
    )
    .fetch_one(executor)
    .await?;

    Ok(decompress_vm_state(res.vm_state))
}

// NOTE - this clears the lock_id when the job state is set to anything other than "running", since that indicates
// the worker is finished with the job. This means subsequent flushes with the same lock_id will fail.
pub async fn flush_job<'c, E>(
    executor: E,
    job_id: Uuid,
    updates: &JobUpdate,
    should_compress_vm_state: bool,
) -> Result<(), QueueError>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    let job_returned = !matches!(updates.state, Some(JobState::Running));
    let lock_id = updates.lock_id;

    let mut query = QueryBuilder::new("UPDATE cyclotron_jobs SET ");
    let mut needs_comma = false;

    if let Some(state) = &updates.state {
        set_helper(&mut query, "state", state, needs_comma);
        needs_comma = true;
    }

    if let Some(queue_name) = &updates.queue_name {
        set_helper(&mut query, "queue_name", queue_name, needs_comma);
        needs_comma = true;
    }

    if let Some(priority) = &updates.priority {
        set_helper(&mut query, "priority", priority, needs_comma);
        needs_comma = true;
    }

    if let Some(scheduled) = &updates.scheduled {
        set_helper(&mut query, "scheduled", scheduled, needs_comma);
        needs_comma = true;
    }

    if let Some(vm_state) = &updates.vm_state {
        if should_compress_vm_state {
            let new_vm_state = compress_vm_state(vm_state.clone())?;
            set_helper(&mut query, "vm_state", new_vm_state.to_owned(), needs_comma)
        } else {
            set_helper(&mut query, "vm_state", vm_state, needs_comma)
        }
        needs_comma = true;
    }

    if let Some(metadata) = &updates.metadata {
        set_helper(&mut query, "metadata", metadata, needs_comma);
        needs_comma = true;
    }

    if let Some(parameters) = &updates.parameters {
        set_helper(&mut query, "parameters", parameters, needs_comma);
        needs_comma = true;
    }

    if let Some(blob) = &updates.blob {
        set_helper(&mut query, "blob", blob, needs_comma);
        needs_comma = true;
    }

    if job_returned {
        // If we're returning this job, clear the lock id and the heartbeat
        set_helper(&mut query, "lock_id", Option::<Uuid>::None, needs_comma);
        set_helper(
            &mut query,
            "last_heartbeat",
            Option::<DateTime<Utc>>::None,
            true,
        );
    } else {
        // Otherwise, flushing a job update indicates forward progress, so we update the heartbeat
        set_helper(&mut query, "last_heartbeat", Utc::now(), needs_comma);
    }

    query.push(" WHERE id = ");
    query.push_bind(job_id);
    query.push(" AND lock_id = ");
    query.push_bind(lock_id);

    assert_does_update(executor, job_id, lock_id, query.build()).await?;
    Ok(())
}

fn set_helper<'args, T, DB>(
    query: &mut QueryBuilder<'args, DB>,
    column_name: &str,
    value: T,
    needs_comma: bool,
) where
    T: 'args + Encode<'args, DB> + Send + Type<DB>,
    DB: sqlx::Database,
{
    if needs_comma {
        query.push(",");
    }
    query.push(column_name);
    query.push(" = ");
    query.push_bind(value);
}

pub async fn set_heartbeat<'c, E>(
    executor: E,
    job_id: Uuid,
    lock_id: Uuid,
) -> Result<(), QueueError>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    let q = sqlx::query!(
        "UPDATE cyclotron_jobs SET last_heartbeat = NOW() WHERE id = $1 AND lock_id = $2",
        job_id,
        lock_id
    );
    assert_does_update(executor, job_id, lock_id, q).await
}

// Simple wrapper, that just executes a query and returns an InvalidLock error if no rows were affected.
async fn assert_does_update<'c, E>(
    executor: E,
    job_id: Uuid,
    lock_id: Uuid,
    query: Query<'_, sqlx::Postgres, PgArguments>,
) -> Result<(), QueueError>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    let res = query.execute(executor).await?;

    // JobError -> QueueError
    Ok(throw_if_no_rows(res, job_id, lock_id)?)
}
