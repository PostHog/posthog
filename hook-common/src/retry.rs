use std::time;

#[derive(Copy, Clone, Debug)]
/// The retry policy that PgQueue will use to determine how to set scheduled_at when enqueuing a retry.
pub struct RetryPolicy {
    /// Coefficient to multiply initial_interval with for every past attempt.
    backoff_coefficient: u32,
    /// The backoff interval for the first retry.
    initial_interval: time::Duration,
    /// The maximum possible backoff between retries.
    maximum_interval: Option<time::Duration>,
}

impl RetryPolicy {
    pub fn new(
        backoff_coefficient: u32,
        initial_interval: time::Duration,
        maximum_interval: Option<time::Duration>,
    ) -> Self {
        Self {
            backoff_coefficient,
            initial_interval,
            maximum_interval,
        }
    }

    /// Calculate the time until the next retry for a given RetryableJob.
    pub fn time_until_next_retry(
        &self,
        attempt: u32,
        preferred_retry_interval: Option<time::Duration>,
    ) -> time::Duration {
        let candidate_interval = self.initial_interval * self.backoff_coefficient.pow(attempt);

        match (preferred_retry_interval, self.maximum_interval) {
            (Some(duration), Some(max_interval)) => std::cmp::min(
                std::cmp::max(std::cmp::min(candidate_interval, max_interval), duration),
                max_interval,
            ),
            (Some(duration), None) => std::cmp::max(candidate_interval, duration),
            (None, Some(max_interval)) => std::cmp::min(candidate_interval, max_interval),
            (None, None) => candidate_interval,
        }
    }
}

impl Default for RetryPolicy {
    fn default() -> Self {
        Self {
            backoff_coefficient: 2,
            initial_interval: time::Duration::from_secs(1),
            maximum_interval: None,
        }
    }
}
