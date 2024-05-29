use anyhow::Error;
use std::sync::Arc;

use crate::{
    redis::{Client, RedisClient},
    team::{self, Team},
};
use rand::{distributions::Alphanumeric, Rng};

pub fn random_string(prefix: &str, length: usize) -> String {
    let suffix: String = rand::thread_rng()
        .sample_iter(Alphanumeric)
        .take(length)
        .map(char::from)
        .collect();
    format!("{}{}", prefix, suffix)
}

pub async fn insert_new_team_in_redis(client: Arc<RedisClient>) -> Result<Team, Error> {
    let id = rand::thread_rng().gen_range(0..10_000_000);
    let token = random_string("phc_", 12);
    let team = Team {
        id,
        name: "team".to_string(),
        api_token: token,
    };

    let serialized_team = serde_json::to_string(&team)?;
    client
        .set(
            format!(
                "{}{}",
                team::TEAM_TOKEN_CACHE_PREFIX,
                team.api_token.clone()
            ),
            serialized_team,
        )
        .await?;

    Ok(team)
}

pub fn setup_redis_client(url: Option<String>) -> Arc<RedisClient> {
    let redis_url = match url {
        Some(value) => value,
        None => "redis://localhost:6379/".to_string(),
    };
    let client = RedisClient::new(redis_url).expect("Failed to create redis client");
    Arc::new(client)
}
