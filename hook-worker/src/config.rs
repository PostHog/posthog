use std::str::FromStr;
use std::time;

use envconfig::Envconfig;

#[derive(Envconfig, Clone)]
pub struct Config {
    #[envconfig(from = "BIND_HOST", default = "0.0.0.0")]
    pub host: String,

    #[envconfig(from = "BIND_PORT", default = "3301")]
    pub port: u16,

    #[envconfig(default = "postgres://posthog:posthog@localhost:15432/test_database")]
    pub database_url: String,

    #[envconfig(default = "worker")]
    pub worker_name: String,

    #[envconfig(default = "default")]
    pub queue_name: String,

    #[envconfig(default = "100")]
    pub poll_interval: EnvMsDuration,

    #[envconfig(default = "5000")]
    pub request_timeout: EnvMsDuration,

    #[envconfig(default = "1024")]
    pub max_concurrent_jobs: usize,

    #[envconfig(nested = true)]
    pub retry_policy: RetryPolicyConfig,

    #[envconfig(default = "true")]
    pub transactional: bool,
}

impl Config {
    /// Produce a host:port address for binding a TcpListener.
    pub fn bind(&self) -> String {
        format!("{}:{}", self.host, self.port)
    }
}

#[derive(Debug, Clone, Copy)]
pub struct EnvMsDuration(pub time::Duration);

#[derive(Debug, PartialEq, Eq)]
pub struct ParseEnvMsDurationError;

impl FromStr for EnvMsDuration {
    type Err = ParseEnvMsDurationError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        let ms = s.parse::<u64>().map_err(|_| ParseEnvMsDurationError)?;

        Ok(EnvMsDuration(time::Duration::from_millis(ms)))
    }
}

#[derive(Envconfig, Clone)]
pub struct RetryPolicyConfig {
    #[envconfig(default = "2")]
    pub backoff_coefficient: u32,

    #[envconfig(default = "1000")]
    pub initial_interval: EnvMsDuration,

    #[envconfig(default = "100000")]
    pub maximum_interval: EnvMsDuration,

    pub retry_queue_name: Option<String>,
}
