use std::{collections::VecDeque, time::Instant};

pub struct Throttler {
    limit: usize,
    duration: std::time::Duration,

    history: VecDeque<Instant>,
}

impl Throttler {
    pub fn new(limit: usize, duration: std::time::Duration) -> Self {
        Throttler {
            limit,
            duration,
            history: VecDeque::new(),
        }
    }

    pub fn throttle(&mut self) {
        let now = Instant::now();
        self.history.push_back(now);

        while self.history.len() > self.limit {
            let time = self.history.pop_front().unwrap();
            let elapsed = now - time;
            if elapsed < self.duration {
                // Entry not yet expired, put it back and wait
                self.history.push_front(time);
                let wait_time = self.duration - elapsed;
                std::thread::sleep(wait_time);
                // After sleeping, remove the now-expired entry
                self.history.pop_front();
            }
            // Entry was expired, already removed, continue loop
        }
    }
}

impl Iterator for Throttler {
    type Item = ();

    fn next(&mut self) -> Option<()> {
        #[allow(clippy::unit_arg)]
        Some(self.throttle())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    #[test]
    fn new_creates_empty_throttler() {
        let throttler = Throttler::new(5, Duration::from_secs(1));

        assert_eq!(throttler.limit, 5);
        assert_eq!(throttler.duration, Duration::from_secs(1));
        assert!(throttler.history.is_empty());
    }

    #[test]
    fn consume_within_limit_does_not_block() {
        let mut throttler = Throttler::new(5, Duration::from_millis(100));
        let start = Instant::now();

        for _ in 0..5 {
            throttler.throttle();
        }

        assert!(start.elapsed() < Duration::from_millis(50));
        assert_eq!(throttler.history.len(), 5);
    }

    #[test]
    fn consume_exceeding_limit_blocks() {
        let mut throttler = Throttler::new(2, Duration::from_millis(50));
        let start = Instant::now();

        throttler.throttle();
        throttler.throttle();
        throttler.throttle();

        assert!(start.elapsed() >= Duration::from_millis(40));
    }

    #[test]
    fn old_entries_expire_after_duration() {
        let mut throttler = Throttler::new(2, Duration::from_millis(30));

        throttler.throttle();
        throttler.throttle();

        std::thread::sleep(Duration::from_millis(40));

        let start = Instant::now();
        throttler.throttle();

        assert!(start.elapsed() < Duration::from_millis(20));
    }

    #[test]
    fn iterator_returns_unit() {
        let mut throttler = Throttler::new(3, Duration::from_millis(100));

        assert_eq!(throttler.next(), Some(()));
        assert_eq!(throttler.next(), Some(()));
        assert_eq!(throttler.next(), Some(()));
    }

    #[test]
    fn iterator_respects_rate_limit() {
        let mut throttler = Throttler::new(2, Duration::from_millis(50));
        let start = Instant::now();

        throttler.next();
        throttler.next();
        throttler.next();

        assert!(start.elapsed() >= Duration::from_millis(40));
    }

    #[test]
    fn sustained_rate_requires_waiting() {
        let mut throttler = Throttler::new(3, Duration::from_millis(100));
        let start = Instant::now();

        for _ in 0..6 {
            throttler.throttle();
        }

        assert!(start.elapsed() >= Duration::from_millis(90));
    }
}
