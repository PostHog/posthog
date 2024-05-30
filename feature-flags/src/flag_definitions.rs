use serde::{Deserialize, Serialize};
use std::sync::Arc;
use tracing::instrument;

use crate::{
    api::FlagError,
    redis::{Client, CustomRedisError},
};

// TRICKY: This cache data is coming from django-redis. If it ever goes out of sync, we'll bork.
// TODO: Add integration tests across repos to ensure this doesn't happen.
pub const TEAM_FLAGS_CACHE_PREFIX: &str = "posthog:1:team_feature_flags_";

// TODO: Hmm, revisit when dealing with groups, but seems like
// ideal to just treat it as a u8 and do our own validation on top
#[derive(Debug, Deserialize, Serialize)]
pub enum GroupTypeIndex {}

#[derive(Debug, Deserialize, Serialize)]
pub enum OperatorType {
    #[serde(rename = "exact")]
    Exact,
    #[serde(rename = "is_not")]
    IsNot,
    #[serde(rename = "icontains")]
    Icontains,
    #[serde(rename = "not_icontains")]
    NotIcontains,
    #[serde(rename = "regex")]
    Regex,
    #[serde(rename = "not_regex")]
    NotRegex,
    #[serde(rename = "gt")]
    Gt,
    #[serde(rename = "lt")]
    Lt,
    #[serde(rename = "gte")]
    Gte,
    #[serde(rename = "lte")]
    Lte,
    #[serde(rename = "is_set")]
    IsSet,
    #[serde(rename = "is_not_set")]
    IsNotSet,
    #[serde(rename = "is_date_exact")]
    IsDateExact,
    #[serde(rename = "is_date_after")]
    IsDateAfter,
    #[serde(rename = "is_date_before")]
    IsDateBefore,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct PropertyFilter {
    pub key: String,
    pub value: serde_json::Value,
    pub operator: Option<OperatorType>,
    #[serde(rename = "type")]
    pub prop_type: String,
    pub group_type_index: Option<u8>,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct FlagGroupType {
    pub properties: Option<Vec<PropertyFilter>>,
    pub rollout_percentage: Option<f32>,
    pub variant: Option<String>,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct MultivariateFlagVariant {
    pub key: String,
    pub name: Option<String>,
    pub rollout_percentage: f32,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct MultivariateFlagOptions {
    pub variants: Vec<MultivariateFlagVariant>,
}

// TODO: test name with https://www.fileformat.info/info/charset/UTF-16/list.htm values, like '𝖕𝖗𝖔𝖕𝖊𝖗𝖙𝖞': `𝓿𝓪𝓵𝓾𝓮`

#[derive(Debug, Deserialize, Serialize)]
pub struct FlagFilters {
    pub groups: Vec<FlagGroupType>,
    pub multivariate: Option<MultivariateFlagOptions>,
    pub aggregation_group_type_index: Option<u8>,
    pub payloads: Option<serde_json::Value>,
    pub super_groups: Option<Vec<FlagGroupType>>,
}

#[derive(Debug, Deserialize, Serialize)]
pub struct FeatureFlag {
    pub id: i64,
    pub team_id: i64,
    pub name: Option<String>,
    pub key: String,
    pub filters: FlagFilters,
    #[serde(default)]
    pub deleted: bool,
    #[serde(default)]
    pub active: bool,
    #[serde(default)]
    pub ensure_experience_continuity: bool,
}

#[derive(Debug, Deserialize, Serialize)]

pub struct FeatureFlagList {
    pub flags: Vec<FeatureFlag>,
}

impl FeatureFlagList {
    /// Returns feature flags given a team_id

    #[instrument(skip_all)]
    pub async fn from_redis(
        client: Arc<dyn Client + Send + Sync>,
        team_id: i64,
    ) -> Result<FeatureFlagList, FlagError> {
        // TODO: Instead of failing here, i.e. if not in redis, fallback to pg
        let serialized_flags = client
            .get(format!("{TEAM_FLAGS_CACHE_PREFIX}{}", team_id))
            .await
            .map_err(|e| match e {
                CustomRedisError::NotFound => FlagError::TokenValidationError,
                CustomRedisError::PickleError(_) => {
                    tracing::error!("failed to fetch data: {}", e);
                    println!("failed to fetch data: {}", e);
                    FlagError::DataParsingError
                }
                _ => {
                    tracing::error!("Unknown redis error: {}", e);
                    FlagError::RedisUnavailable
                }
            })?;

        let flags_list: Vec<FeatureFlag> =
            serde_json::from_str(&serialized_flags).map_err(|e| {
                tracing::error!("failed to parse data to flags list: {}", e);
                println!("failed to parse data: {}", e);

                FlagError::DataParsingError
            })?;

        Ok(FeatureFlagList { flags: flags_list })
    }
}

#[cfg(test)]
mod tests {
    use rand::Rng;

    use super::*;
    use crate::test_utils::{
        insert_flags_for_team_in_redis, insert_new_team_in_redis, setup_redis_client,
    };

    #[tokio::test]
    async fn test_fetch_flags_from_redis() {
        let client = setup_redis_client(None);

        let team = insert_new_team_in_redis(client.clone()).await.unwrap();

        insert_flags_for_team_in_redis(client.clone(), team.id, None)
            .await
            .expect("Failed to insert flags");

        let flags_from_redis = FeatureFlagList::from_redis(client.clone(), team.id)
            .await
            .unwrap();
        assert_eq!(flags_from_redis.flags.len(), 1);
        let flag = flags_from_redis.flags.get(0).unwrap();
        assert_eq!(flag.key, "flag1");
        assert_eq!(flag.team_id, team.id);
        assert_eq!(flag.filters.groups.len(), 1);
        assert_eq!(flag.filters.groups[0].properties.as_ref().unwrap().len(), 1);
    }

    #[tokio::test]
    async fn test_fetch_invalid_team_from_redis() {
        let client = setup_redis_client(None);

        match FeatureFlagList::from_redis(client.clone(), 1234).await {
            Err(FlagError::TokenValidationError) => (),
            _ => panic!("Expected TokenValidationError"),
        };
    }

    #[tokio::test]
    async fn test_cant_connect_to_redis_error_is_not_token_validation_error() {
        let client = setup_redis_client(Some("redis://localhost:1111/".to_string()));

        match FeatureFlagList::from_redis(client.clone(), 1234).await {
            Err(FlagError::RedisUnavailable) => (),
            _ => panic!("Expected RedisUnavailable"),
        };
    }
}
