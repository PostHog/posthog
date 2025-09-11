use uuid::Uuid;

#[derive(Debug, thiserror::Error)]
pub enum QueueError {
    #[error("sqlx error: {0}")]
    SqlxError(#[from] sqlx::Error),
    #[error("Shard over capacity {0} for this manager, insert aborted")]
    ShardFull(u64),
    #[error("Timed waiting for shard to have capacity")]
    TimedOutWaitingForCapacity,
    #[error(transparent)]
    JobError(#[from] JobError),
    #[error("vm_state compression error: {0}")]
    CompressionError(String),
    #[error("writing in-mem CSV buffer at {0}: {1}")]
    CsvError(&'static str, csv::Error),
}

#[derive(Debug, thiserror::Error)]
pub enum JobError {
    #[error("Unknown job id: {0}")]
    UnknownJobId(Uuid),
    #[error("Invalid lock id: {0} for job {1}")]
    InvalidLock(Uuid, Uuid),
    #[error("Cannot flush job {0} without a next state")]
    FlushWithoutNextState(Uuid),
    #[error("Deadline to flush update for job {0} exceeded")]
    DeadlineExceeded(Uuid),
    #[error("Update dropped before being flushed.")]
    UpdateDropped,
    #[error("vm_state compression error: {0}")]
    CompressionError(String),
}
