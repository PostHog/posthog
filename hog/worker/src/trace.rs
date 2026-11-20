// Phase timings on stderr when HOG_WORKER_TRACE is set, to find where a large build spends time.

use std::{sync::Mutex, time::Instant};

const TRACE_VARIABLE: &str = "HOG_WORKER_TRACE";

pub struct Trace(Option<Mutex<Instant>>);

impl Trace {
    pub fn from_environment() -> Self {
        Trace(std::env::var_os(TRACE_VARIABLE).map(|_| Mutex::new(Instant::now())))
    }

    pub fn mark(&self, phase: &str) {
        if let Some(last) = &self.0 {
            let mut last = last.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
            eprintln!("hog-worker {phase}: {:.2}s", last.elapsed().as_secs_f64());
            *last = Instant::now();
        }
    }
}
