use std::time::Duration;

use anyhow::Result;
use async_trait::async_trait;
use redis::AsyncCommands;
use tokio::time::timeout;

// average for all commands is <10ms, check grafana
const REDIS_TIMEOUT_MILLISECS: u64 = 10;

/// A simple redis wrapper
/// Copied from capture/src/redis.rs.
/// TODO: Modify this to support hincrby, get, and set commands.

#[async_trait]
pub trait Client {
    // A very simplified wrapper, but works for our usage
    async fn zrangebyscore(&self, k: String, min: String, max: String) -> Result<Vec<String>>;
}

pub struct RedisClient {
    client: redis::Client,
}

impl RedisClient {
    pub fn new(addr: String) -> Result<RedisClient> {
        let client = redis::Client::open(addr)?;

        Ok(RedisClient { client })
    }
}

#[async_trait]
impl Client for RedisClient {
    async fn zrangebyscore(&self, k: String, min: String, max: String) -> Result<Vec<String>> {
        let mut conn = self.client.get_async_connection().await?;

        let results = conn.zrangebyscore(k, min, max);
        let fut = timeout(Duration::from_secs(REDIS_TIMEOUT_MILLISECS), results).await?;

        Ok(fut?)
    }
}

// TODO: Find if there's a better way around this.
#[derive(Clone)]
pub struct MockRedisClient {
    zrangebyscore_ret: Vec<String>,
}

impl MockRedisClient {
    pub fn new() -> MockRedisClient {
        MockRedisClient {
            zrangebyscore_ret: Vec::new(),
        }
    }

    pub fn zrangebyscore_ret(&mut self, ret: Vec<String>) -> Self {
        self.zrangebyscore_ret = ret;

        self.clone()
    }
}

impl Default for MockRedisClient {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl Client for MockRedisClient {
    // A very simplified wrapper, but works for our usage
    async fn zrangebyscore(&self, _k: String, _min: String, _max: String) -> Result<Vec<String>> {
        Ok(self.zrangebyscore_ret.clone())
    }
}
