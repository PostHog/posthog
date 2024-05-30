use anyhow::Error;
use serde_json::json;
use std::sync::Arc;

use crate::{
    flag_definitions,
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

pub async fn insert_flags_for_team_in_redis(
    client: Arc<RedisClient>,
    team_id: i64,
    json_value: Option<String>,
) -> Result<(), Error> {
    let payload = match json_value {
        Some(value) => value,
        None => json!([{
            "id": 1,
            "key": "flag1",
            "name": "flag1 description",
            "active": true,
            "deleted": false,
            "team_id": team_id,
            "filters": {
                "groups": [
                    {
                        "properties": [
                            {
                                "key": "email",
                                "value": "a@b.com",
                                "type": "person",
                            },
                        ]
                    },
                ],
            },
        }])
        .to_string(),
    };

    client
        .set(
            format!("{}{}", flag_definitions::TEAM_FLAGS_CACHE_PREFIX, team_id),
            payload,
        )
        .await?;

    Ok(())
}

pub fn setup_redis_client(url: Option<String>) -> Arc<RedisClient> {
    let redis_url = match url {
        Some(value) => value,
        None => "redis://localhost:6379/".to_string(),
    };
    let client = RedisClient::new(redis_url).expect("Failed to create redis client");
    Arc::new(client)
}
