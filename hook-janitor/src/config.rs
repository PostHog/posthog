use envconfig::Envconfig;

#[derive(Envconfig)]
pub struct Config {
    #[envconfig(from = "BIND_HOST", default = "0.0.0.0")]
    pub host: String,

    #[envconfig(from = "BIND_PORT", default = "3302")]
    pub port: u16,

    #[envconfig(default = "postgres://posthog:posthog@localhost:15432/test_database")]
    pub database_url: String,

    #[envconfig(default = "30")]
    pub cleanup_interval_secs: u64,

    // The cleanup task needs to have special knowledge of the queue it's cleaning up. This is so it
    // can do things like flush the proper app_metrics or plugin_log_entries, and so it knows what
    // to expect in the job's payload JSONB column.
    #[envconfig(default = "webhooks")]
    pub mode: String,

    #[envconfig(nested = true)]
    pub kafka: KafkaConfig,
}

#[derive(Envconfig, Clone)]
pub struct KafkaConfig {
    #[envconfig(default = "20")]
    pub kafka_producer_linger_ms: u32, // Maximum time between producer batches during low traffic

    #[envconfig(default = "400")]
    pub kafka_producer_queue_mib: u32, // Size of the in-memory producer queue in mebibytes

    #[envconfig(default = "20000")]
    pub kafka_message_timeout_ms: u32, // Time before we stop retrying producing a message: 20 seconds

    #[envconfig(default = "none")]
    pub kafka_compression_codec: String, // none, gzip, snappy, lz4, zstd

    #[envconfig(default = "false")]
    pub kafka_tls: bool,

    #[envconfig(default = "clickhouse_app_metrics")]
    pub app_metrics_topic: String,

    #[envconfig(default = "plugin_log_entries")]
    pub plugin_log_entries_topic: String,

    pub kafka_hosts: String,
}

impl Config {
    pub fn bind(&self) -> String {
        format!("{}:{}", self.host, self.port)
    }
}
