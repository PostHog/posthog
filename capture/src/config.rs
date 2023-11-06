use std::net::SocketAddr;

use envconfig::Envconfig;

#[derive(Envconfig, Clone)]
pub struct Config {
    #[envconfig(default = "false")]
    pub print_sink: bool,
    #[envconfig(default = "127.0.0.1:3000")]
    pub address: SocketAddr,
    pub redis_url: String,
    #[envconfig(default = "true")]
    pub export_prometheus: bool,

    pub kafka_hosts: String,
    pub kafka_topic: String,
    #[envconfig(default = "false")]
    pub kafka_tls: bool,
}
