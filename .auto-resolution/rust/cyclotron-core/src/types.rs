use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::str::FromStr;
use uuid::Uuid;

pub type Bytes = Vec<u8>;

#[derive(Debug, Deserialize, Serialize, sqlx::Type)]
#[serde(rename_all = "lowercase")]
#[sqlx(type_name = "JobState", rename_all = "lowercase")]
pub enum JobState {
    Available,
    Running,
    Completed,
    Failed,
    Paused,
}

impl FromStr for JobState {
    type Err = ();

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s {
            "available" => Ok(JobState::Available),
            "running" => Ok(JobState::Running),
            "completed" => Ok(JobState::Completed),
            "failed" => Ok(JobState::Failed),
            _ => Err(()),
        }
    }
}

// The chunk of data needed to enqueue a job
#[derive(Debug, Deserialize, Serialize, Clone, Eq, PartialEq)]
pub struct JobInit {
    pub team_id: i32,
    pub queue_name: String,
    pub priority: i16,
    pub scheduled: DateTime<Utc>,
    pub function_id: Option<Uuid>,
    pub vm_state: Option<Bytes>,
    pub parameters: Option<Bytes>,
    pub blob: Option<Bytes>,
    pub metadata: Option<Bytes>,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct Job {
    // Job metadata
    pub id: Uuid,
    pub team_id: i32,
    pub function_id: Option<Uuid>, // Some jobs might not come from hog, and it doesn't /kill/ use to support that
    pub created: DateTime<Utc>,

    // Queue bookkeeping
    // This will be set for any worker that ever has a job in the "running" state (so any worker that dequeues a job)
    // but I don't want to do the work to encode that in the type system right now - later it should be
    pub lock_id: Option<Uuid>,
    pub last_heartbeat: Option<DateTime<Utc>>,
    pub janitor_touch_count: i16,
    pub transition_count: i16,
    pub last_transition: DateTime<Utc>,

    // Virtual queue components
    pub queue_name: String, // We can have multiple "virtual queues" workers pull from

    // Job availability
    pub state: JobState,
    pub priority: i16, // For sorting "available" jobs. Lower is higher priority
    pub scheduled: DateTime<Utc>,

    // Job data
    pub vm_state: Option<Bytes>, // The state of the VM this job is running on (if it exists)
    pub metadata: Option<Bytes>, // Additional fields a worker can tack onto a job, for e.g. tracking some state across retries (or number of retries in general by a given class of worker)
    pub parameters: Option<Bytes>, // The actual parameters of the job (function args for a hog function, http request for a fetch function)
    pub blob: Option<Bytes>, // An additional, binary, parameter field (for things like fetch request body)
}

// A struct representing a set of updates for a job. Outer none values mean "don't update this field",
// with nested none values meaning "set this field to null" for nullable fields
#[derive(Debug, Deserialize, Serialize)]
pub struct JobUpdate {
    pub lock_id: Uuid, // The ID of the lock acquired when this worker dequeued the job, required for any update to be valid
    pub state: Option<JobState>,
    pub queue_name: Option<String>,
    pub priority: Option<i16>,
    pub scheduled: Option<DateTime<Utc>>,
    pub vm_state: Option<Option<Bytes>>,
    pub metadata: Option<Option<Bytes>>,
    pub parameters: Option<Option<Bytes>>,
    pub blob: Option<Option<Bytes>>,
    #[serde(skip)]
    pub last_heartbeat: Option<DateTime<Utc>>,
}

impl JobUpdate {
    pub fn new(lock_id: Uuid) -> Self {
        Self {
            lock_id,
            state: None,
            queue_name: None,
            priority: None,
            scheduled: None,
            vm_state: None,
            metadata: None,
            parameters: None,
            blob: None,
            last_heartbeat: Some(Utc::now()), // Dequeueing a job always touches the heartbeat
        }
    }
}

// Result of janitor's `delete_completed_and_failed_jobs`
#[derive(sqlx::FromRow, Debug)]
pub struct AggregatedDelete {
    // `last_transition` column truncated to the hour.
    pub hour: DateTime<Utc>,
    pub team_id: i64,
    pub function_id: Option<String>,
    pub state: String,
    pub count: i64,
}
