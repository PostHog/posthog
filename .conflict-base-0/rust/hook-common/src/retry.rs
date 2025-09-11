//! # Retry
//!
//! Module providing a `RetryPolicy` struct to configure job retrying.
use std::time;

#[derive(Clone, Debug)]
/// A retry policy to determine retry parameters for a job.
pub struct RetryPolicy {
    /// Coefficient to multiply initial_interval with for every past attempt.
    pub backoff_coefficient: u32,
    /// The backoff interval for the first retry.
    pub initial_interval: time::Duration,
    /// The maximum possible backoff between retries.
    pub maximum_interval: Option<time::Duration>,
    /// An optional queue to send WebhookJob retries to.
    pub queue: Option<String>,
}

impl RetryPolicy {
    /// Initialize a `RetryPolicyBuilder`.
    pub fn build(backoff_coefficient: u32, initial_interval: time::Duration) -> RetryPolicyBuilder {
        RetryPolicyBuilder::new(backoff_coefficient, initial_interval)
    }

    /// Determine interval for retrying at a given attempt number.
    /// If not `None`, this method will respect `preferred_retry_interval` as long as it falls within `candidate_interval <= preferred_retry_interval <= maximum_interval`.
    pub fn retry_interval(
        &self,
        attempt: u32,
        preferred_retry_interval: Option<time::Duration>,
    ) -> time::Duration {
        let candidate_interval =
            self.initial_interval * self.backoff_coefficient.pow(attempt.saturating_sub(1));

        match (preferred_retry_interval, self.maximum_interval) {
            (Some(duration), Some(max_interval)) => {
                let min_interval_allowed = std::cmp::min(candidate_interval, max_interval);

                if min_interval_allowed <= duration && duration <= max_interval {
                    duration
                } else {
                    min_interval_allowed
                }
            }
            (Some(duration), None) => std::cmp::max(candidate_interval, duration),
            (None, Some(max_interval)) => std::cmp::min(candidate_interval, max_interval),
            (None, None) => candidate_interval,
        }
    }

    /// Determine the queue to be used for retrying.
    /// Only whether a queue is configured in this RetryPolicy is used to determine which queue to use for retrying.
    /// This may be extended in the future to support more decision parameters.
    pub fn retry_queue<'s>(&'s self, current_queue: &'s str) -> &'s str {
        if let Some(new_queue) = &self.queue {
            new_queue
        } else {
            current_queue
        }
    }
}

impl Default for RetryPolicy {
    fn default() -> Self {
        RetryPolicyBuilder::default().provide()
    }
}

/// Builder pattern struct to provide a `RetryPolicy`.
pub struct RetryPolicyBuilder {
    /// Coefficient to multiply initial_interval with for every past attempt.
    pub backoff_coefficient: u32,
    /// The backoff interval for the first retry.
    pub initial_interval: time::Duration,
    /// The maximum possible backoff between retries.
    pub maximum_interval: Option<time::Duration>,
    /// An optional queue to send WebhookJob retries to.
    pub queue: Option<String>,
}

impl Default for RetryPolicyBuilder {
    fn default() -> Self {
        Self {
            backoff_coefficient: 2,
            initial_interval: time::Duration::from_secs(1),
            maximum_interval: None,
            queue: None,
        }
    }
}

impl RetryPolicyBuilder {
    pub fn new(backoff_coefficient: u32, initial_interval: time::Duration) -> Self {
        Self {
            backoff_coefficient,
            initial_interval,
            ..RetryPolicyBuilder::default()
        }
    }

    pub fn maximum_interval(mut self, interval: time::Duration) -> RetryPolicyBuilder {
        self.maximum_interval = Some(interval);
        self
    }

    pub fn queue(mut self, queue: &str) -> RetryPolicyBuilder {
        self.queue = Some(queue.to_owned());
        self
    }

    /// Provide a `RetryPolicy` according to build parameters provided thus far.
    pub fn provide(&self) -> RetryPolicy {
        RetryPolicy {
            backoff_coefficient: self.backoff_coefficient,
            initial_interval: self.initial_interval,
            maximum_interval: self.maximum_interval,
            queue: self.queue.clone(),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_constant_retry_interval() {
        let retry_policy = RetryPolicy::build(1, time::Duration::from_secs(2)).provide();
        let first_interval = retry_policy.retry_interval(1, None);
        let second_interval = retry_policy.retry_interval(2, None);
        let third_interval = retry_policy.retry_interval(3, None);

        assert_eq!(first_interval, time::Duration::from_secs(2));
        assert_eq!(second_interval, time::Duration::from_secs(2));
        assert_eq!(third_interval, time::Duration::from_secs(2));
    }

    #[test]
    fn test_retry_interval_never_exceeds_maximum() {
        let retry_policy = RetryPolicy::build(2, time::Duration::from_secs(2))
            .maximum_interval(time::Duration::from_secs(4))
            .provide();
        let first_interval = retry_policy.retry_interval(1, None);
        let second_interval = retry_policy.retry_interval(2, None);
        let third_interval = retry_policy.retry_interval(3, None);
        let fourth_interval = retry_policy.retry_interval(4, None);

        assert_eq!(first_interval, time::Duration::from_secs(2));
        assert_eq!(second_interval, time::Duration::from_secs(4));
        assert_eq!(third_interval, time::Duration::from_secs(4));
        assert_eq!(fourth_interval, time::Duration::from_secs(4));
    }

    #[test]
    fn test_retry_interval_increases_with_coefficient() {
        let retry_policy = RetryPolicy::build(2, time::Duration::from_secs(2)).provide();
        let first_interval = retry_policy.retry_interval(1, None);
        let second_interval = retry_policy.retry_interval(2, None);
        let third_interval = retry_policy.retry_interval(3, None);

        assert_eq!(first_interval, time::Duration::from_secs(2));
        assert_eq!(second_interval, time::Duration::from_secs(4));
        assert_eq!(third_interval, time::Duration::from_secs(8));
    }

    #[test]
    fn test_retry_interval_respects_preferred() {
        let retry_policy = RetryPolicy::build(1, time::Duration::from_secs(2)).provide();
        let preferred = time::Duration::from_secs(999);
        let first_interval = retry_policy.retry_interval(1, Some(preferred));
        let second_interval = retry_policy.retry_interval(2, Some(preferred));
        let third_interval = retry_policy.retry_interval(3, Some(preferred));

        assert_eq!(first_interval, preferred);
        assert_eq!(second_interval, preferred);
        assert_eq!(third_interval, preferred);
    }

    #[test]
    fn test_retry_interval_ignores_small_preferred() {
        let retry_policy = RetryPolicy::build(1, time::Duration::from_secs(5)).provide();
        let preferred = time::Duration::from_secs(2);
        let first_interval = retry_policy.retry_interval(1, Some(preferred));
        let second_interval = retry_policy.retry_interval(2, Some(preferred));
        let third_interval = retry_policy.retry_interval(3, Some(preferred));

        assert_eq!(first_interval, time::Duration::from_secs(5));
        assert_eq!(second_interval, time::Duration::from_secs(5));
        assert_eq!(third_interval, time::Duration::from_secs(5));
    }

    #[test]
    fn test_retry_interval_ignores_large_preferred() {
        let retry_policy = RetryPolicy::build(2, time::Duration::from_secs(2))
            .maximum_interval(time::Duration::from_secs(4))
            .provide();
        let preferred = time::Duration::from_secs(10);
        let first_interval = retry_policy.retry_interval(1, Some(preferred));
        let second_interval = retry_policy.retry_interval(2, Some(preferred));
        let third_interval = retry_policy.retry_interval(3, Some(preferred));

        assert_eq!(first_interval, time::Duration::from_secs(2));
        assert_eq!(second_interval, time::Duration::from_secs(4));
        assert_eq!(third_interval, time::Duration::from_secs(4));
    }

    #[test]
    fn test_returns_retry_queue_if_set() {
        let retry_queue_name = "retry_queue".to_owned();
        let retry_policy = RetryPolicy::build(0, time::Duration::from_secs(0))
            .queue(&retry_queue_name)
            .provide();
        let current_queue = "queue".to_owned();

        assert_eq!(retry_policy.retry_queue(&current_queue), retry_queue_name);
    }

    #[test]
    fn test_returns_queue_if_retry_queue_not_set() {
        let retry_policy = RetryPolicy::build(0, time::Duration::from_secs(0)).provide();
        let current_queue = "queue".to_owned();

        assert_eq!(retry_policy.retry_queue(&current_queue), current_queue);
    }
}
