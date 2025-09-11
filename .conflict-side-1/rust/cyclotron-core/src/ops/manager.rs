use chrono::{DateTime, Utc};
use sqlx::{postgres::PgPoolCopyExt, Pool, Postgres};
use uuid::Uuid;

use crate::{
    error::QueueError,
    ops::compress::compress_vm_state,
    types::{Bytes, JobInit, JobState},
};
use common_metrics::inc;

const ESTIMATED_RECORD_SIZE: usize = 1024;

const COPY_IN_STMT: &str = r#"COPY cyclotron_jobs
    (id, team_id, function_id, created, lock_id, last_heartbeat, janitor_touch_count,
     transition_count, last_transition, queue_name, state, scheduled, priority, vm_state,
     metadata, parameters, blob)
    FROM STDIN WITH (FORMAT CSV, ENCODING 'UTF8')"#;

pub async fn create_job<'c, E>(
    executor: E,
    mut data: JobInit,
    should_compress_vm_state: bool,
) -> Result<Uuid, QueueError>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    let id = Uuid::now_v7();

    if should_compress_vm_state {
        data.vm_state = compress_vm_state(data.vm_state)?;
    }

    sqlx::query!(
        r#"
INSERT INTO cyclotron_jobs
    (
        id,
        team_id,
        function_id,
        created,
        lock_id,
        last_heartbeat,
        janitor_touch_count,
        transition_count,
        last_transition,
        queue_name,
        state,
        scheduled,
        priority,
        vm_state,
        metadata,
        parameters,
        blob
    )
VALUES
    ($1, $2, $3, NOW(), NULL, NULL, 0, 0, NOW(), $4, $5, $6, $7, $8, $9, $10, $11)
    "#,
        id,
        data.team_id,
        data.function_id,
        data.queue_name,
        JobState::Available as _,
        data.scheduled,
        data.priority,
        data.vm_state,
        data.metadata,
        data.parameters,
        data.blob
    )
    .execute(executor)
    .await?;

    Ok(id)
}

pub async fn bulk_create_jobs_upsert<'c, E>(
    executor: E,
    jobs: Vec<JobInit>,
    should_compress_vm_state: bool,
) -> Result<Vec<Uuid>, QueueError>
where
    E: sqlx::Executor<'c, Database = sqlx::Postgres>,
{
    let now = Utc::now();
    // Flatten these jobs into a series of vecs of arguments PG can unnest
    let mut ids = Vec::with_capacity(jobs.len());
    let mut team_ids = Vec::with_capacity(jobs.len());
    let mut function_ids = Vec::with_capacity(jobs.len());
    let mut created_at = Vec::with_capacity(jobs.len());
    let mut lock_ids = Vec::with_capacity(jobs.len());
    let mut last_heartbeats = Vec::with_capacity(jobs.len());
    let mut janitor_touch_counts = Vec::with_capacity(jobs.len());
    let mut transition_counts = Vec::with_capacity(jobs.len());
    let mut last_transitions = Vec::with_capacity(jobs.len());
    let mut queue_names = Vec::with_capacity(jobs.len());
    let mut states = Vec::with_capacity(jobs.len());
    let mut scheduleds = Vec::with_capacity(jobs.len());
    let mut priorities = Vec::with_capacity(jobs.len());
    let mut vm_states = Vec::with_capacity(jobs.len());
    let mut metadatas = Vec::with_capacity(jobs.len());
    let mut parameters = Vec::with_capacity(jobs.len());
    let mut blob = Vec::with_capacity(jobs.len());

    for d in &jobs {
        let vm_state = d.vm_state.clone();
        if should_compress_vm_state {
            vm_states.push(compress_vm_state(vm_state)?);
        } else {
            vm_states.push(vm_state);
        }

        ids.push(Uuid::now_v7());
        team_ids.push(d.team_id);
        function_ids.push(d.function_id);
        created_at.push(now);
        lock_ids.push(None::<Uuid>);
        last_heartbeats.push(None::<DateTime<Utc>>);
        janitor_touch_counts.push(0);
        transition_counts.push(0);
        last_transitions.push(now);
        queue_names.push(d.queue_name.clone());
        states.push(JobState::Available);
        scheduleds.push(d.scheduled);
        priorities.push(d.priority);
        metadatas.push(d.metadata.clone());
        parameters.push(d.parameters.clone());
        blob.push(d.blob.clone());
    }

    // Using the "unnest" function to turn an array of rows into a set of rows
    sqlx::query(
        r#"
INSERT INTO cyclotron_jobs
    (
        id,
        team_id,
        function_id,
        created,
        lock_id,
        last_heartbeat,
        janitor_touch_count,
        transition_count,
        last_transition,
        queue_name,
        state,
        scheduled,
        priority,
        vm_state,
        metadata,
        parameters,
        blob
    )
SELECT *
FROM UNNEST(
        $1,
        $2,
        $3,
        $4,
        $5,
        $6,
        $7,
        $8,
        $9,
        $10,
        $11,
        $12,
        $13,
        $14,
        $15,
        $16,
        $17
    )
"#,
    )
    .bind(&ids)
    .bind(team_ids)
    .bind(function_ids)
    .bind(created_at)
    .bind(lock_ids)
    .bind(last_heartbeats)
    .bind(janitor_touch_counts)
    .bind(transition_counts)
    .bind(last_transitions)
    .bind(queue_names)
    .bind(states)
    .bind(scheduleds)
    .bind(priorities)
    .bind(vm_states)
    .bind(metadatas)
    .bind(parameters)
    .bind(blob)
    .execute(executor)
    .await?;

    Ok(ids)
}

// wraps CSV rows to be encoded and batch written
// to Postgres as part of a COPY FROM STDIN stmt
#[derive(Debug, serde::Serialize)]
struct CopyFromJobInit {
    id: Uuid,
    team_id: i32,
    function_id: Option<Uuid>,
    created: DateTime<Utc>,
    lock_id: Option<Uuid>,
    last_heartbeat: Option<DateTime<Utc>>,
    janitor_touch_count: i32,
    transition_count: i32,
    last_transition: DateTime<Utc>,
    queue_name: String,
    job_state: JobState,
    scheduled: DateTime<Utc>,
    priority: i16,
    vm_state: Option<String>,
    metadata: Option<String>,
    parameters: Option<String>,
    blob: Option<String>,
}

pub async fn bulk_create_jobs_copy(
    pool: &Pool<Postgres>,
    jobs: Vec<JobInit>,
    should_compress_vm_state: bool,
) -> Result<Vec<Uuid>, QueueError> {
    let mut ids = Vec::with_capacity(jobs.len());
    let now = Utc::now();

    // set up CSV in mem buffer for capturing the row data; try to
    // avoid too many buffer extension allocations as we fill it
    let estimated_buffer_size = jobs.len() * ESTIMATED_RECORD_SIZE;
    let buffer = Bytes::with_capacity(estimated_buffer_size);
    let mut csv_writer = csv::WriterBuilder::new()
        .delimiter(b',')
        .has_headers(false)
        .from_writer(buffer);

    for j in jobs {
        let new_id = Uuid::now_v7();
        ids.push(new_id);

        let mut vm_state = j.vm_state;
        if should_compress_vm_state {
            vm_state = compress_vm_state(vm_state)?;
        }

        let cj = CopyFromJobInit {
            id: new_id,
            team_id: j.team_id,
            function_id: j.function_id,
            created: now,
            lock_id: None::<Uuid>,
            last_heartbeat: None::<DateTime<Utc>>,
            janitor_touch_count: 0,
            transition_count: 0,
            last_transition: now,
            queue_name: j.queue_name,
            job_state: JobState::Available,
            scheduled: j.scheduled,
            priority: j.priority,
            vm_state: encode_pg_bytea(vm_state),
            metadata: encode_pg_bytea(j.metadata),
            parameters: encode_pg_bytea(j.parameters),
            blob: encode_pg_bytea(j.blob),
        };

        csv_writer
            .serialize(cj)
            .map_err(|e| QueueError::CsvError("csv_serialize", e))?;
    }

    csv_writer
        .flush()
        .map_err(|e| QueueError::CsvError("csv_flush", e.into()))?;

    let mut stream = pool.copy_in_raw(COPY_IN_STMT).await?;
    let result = stream.send(&csv_writer.get_ref()[..]).await;
    if let Err(e) = result {
        let _unused = stream
            .abort(format!("failed to send COPY IN record: {e}"))
            .await;
        return Err(QueueError::SqlxError(e));
    }

    let _unused = result.unwrap();
    let rows_affected = stream.finish().await.map_err(QueueError::SqlxError)?;
    inc("bulk_create_jobs_copy_rows_affected", &[], rows_affected);

    Ok(ids)
}

// COPY FROM STDIN with CSV input method must encode BYTEA binary blobs
// as specially-formatted UTF-8 Strings. When the Option is None,
// the CSV field will be empty and the DB column will record a NULL value
fn encode_pg_bytea(buffer: Option<Bytes>) -> Option<String> {
    buffer.map(|bs| format!("\\x{}", hex::encode(bs)))
}
