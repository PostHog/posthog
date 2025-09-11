use crate::flags::flag_matching::FeatureFlagMatch;
use crate::flags::flag_models::FeatureFlag;
use crate::{flags::flag_match_reason::FeatureFlagMatchReason, site_apps::WebJsUrl};
use serde::{de, Deserialize, Deserializer, Serialize};
use serde_json::Value;
use std::{collections::HashMap, fmt, str::FromStr};
use uuid::Uuid;

#[derive(Debug, PartialEq, Eq, Deserialize, Serialize)]
pub enum FlagsResponseCode {
    Ok = 1,
}

#[derive(Clone, Debug, PartialEq, Eq, Deserialize, Serialize)]
#[serde(untagged)]
pub enum FlagValue {
    Boolean(bool),
    String(String),
}

#[derive(Debug, PartialEq, Eq, Deserialize, Serialize)]
pub struct LinkedFlag {
    pub flag: String,
    pub variant: String,
}

#[derive(Debug, Clone, PartialEq, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SiteApp {
    pub id: i64,
    pub url: String,
}

#[derive(Debug, Clone, Copy, Deserialize, Serialize, PartialEq, Eq, Default)]
#[serde(rename_all = "lowercase")]
pub enum Compression {
    #[serde(alias = "gzip-js")]
    Gzip,
    Base64,
    #[default]
    #[serde(other)]
    Unsupported,
}

impl FromStr for Compression {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.to_lowercase().as_str() {
            "gzip" | "gzip-js" => Ok(Compression::Gzip),
            "base64" => Ok(Compression::Base64),
            _ => Ok(Compression::Unsupported),
        }
    }
}

impl Compression {
    pub fn as_str(&self) -> &'static str {
        match self {
            Compression::Gzip => "gzip",
            Compression::Base64 => "base64",
            Compression::Unsupported => "unsupported",
        }
    }
}

#[derive(Clone, Deserialize, Default)]
pub struct FlagsQueryParams {
    /// Optional API version identifier, defaults to None (which returns a legacy response)
    #[serde(alias = "v", default, deserialize_with = "empty_string_as_none")]
    pub version: Option<String>,

    /// Compression type for the incoming request
    #[serde(default, deserialize_with = "empty_string_as_none")]
    pub compression: Option<Compression>,

    /// Library version (alias: "ver")
    #[serde(alias = "ver", default, deserialize_with = "empty_string_as_none")]
    pub lib_version: Option<String>,

    /// Optional timestamp indicating when the request was sent
    #[serde(
        alias = "_",
        default,
        deserialize_with = "deserialize_optional_timestamp"
    )]
    pub sent_at: Option<i64>,

    /// Optional boolean indicating whether to only evaluate survey feature flags
    #[serde(default, deserialize_with = "deserialize_optional_bool")]
    pub only_evaluate_survey_feature_flags: Option<bool>,

    /// Optional boolean indicating whether to include the config field in the response
    /// This lets us have parity with the legacy /decide endpoint so that we can support
    /// JS and other mobile clients need more config data than /flags supplied originally.
    /// e.g. https://us.posthog.com/flags?v=2&config=true
    #[serde(default, deserialize_with = "deserialize_optional_bool")]
    pub config: Option<bool>,
}

#[derive(Debug, PartialEq, Eq, Deserialize, Serialize)]
#[serde(untagged)]
pub enum ServiceResponse {
    Default(LegacyFlagsResponse),
    V2(FlagsResponse),
    DecideV1(DecideV1Response),
    DecideV2(DecideV2Response),
}

#[derive(Debug, PartialEq, Eq, Deserialize, Serialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct ConfigResponse {
    // Config fields - only present when config=true
    /// Supported compression algorithms
    #[serde(skip_serializing_if = "Vec::is_empty", default)]
    pub supported_compression: Vec<String>,

    /// If set, disables autocapture
    #[serde(skip_serializing_if = "Option::is_none")]
    #[serde(rename = "autocapture_opt_out")]
    pub autocapture_opt_out: Option<bool>,

    /// Originally capturePerformance was replay only and so boolean true
    /// is equivalent to { network_timing: true }
    /// now capture performance can be separately enabled within replay
    /// and as a standalone web vitals tracker
    /// people can have them enabled separately
    /// they work standalone but enhance each other
    /// TODO: deprecate this so we make a new config that doesn't need this explanation
    #[serde(skip_serializing_if = "Option::is_none")]
    pub capture_performance: Option<Value>,

    #[serde(skip_serializing_if = "Option::is_none")]
    pub config: Option<Value>,

    /// Whether we should use a custom endpoint for analytics
    ///
    /// Default: { endpoint: "/e" }
    #[serde(skip_serializing_if = "Option::is_none")]
    pub analytics: Option<AnalyticsConfig>,

    /// Whether the `$elements_chain` property should be sent as a string or as an array
    ///
    /// Default: false
    #[serde(skip_serializing_if = "Option::is_none")]
    pub elements_chain_as_string: Option<bool>,

    /// This is currently in development and may have breaking changes without a major version bump
    #[serde(skip_serializing_if = "Option::is_none")]
    pub autocapture_exceptions: Option<Value>,

    /// Session recording configuration options
    #[serde(skip_serializing_if = "Option::is_none")]
    pub session_recording: Option<SessionRecordingField>,

    /// Whether surveys are enabled
    #[serde(skip_serializing_if = "Option::is_none")]
    pub surveys: Option<Value>,

    /// Parameters for the toolbar
    #[serde(skip_serializing_if = "Option::is_none", default)]
    pub toolbar_params: Option<Value>,

    /// Whether the user is authenticated
    #[serde(skip_serializing_if = "Option::is_none")]
    pub is_authenticated: Option<bool>,

    /// List of site apps with their IDs and URLs
    #[serde(skip_serializing_if = "Option::is_none")]
    pub site_apps: Option<Vec<WebJsUrl>>,

    /// Whether heatmaps are enabled
    #[serde(skip_serializing_if = "Option::is_none")]
    pub heatmaps: Option<bool>,

    #[serde(skip_serializing_if = "Option::is_none")]
    pub flags_persistence_default: Option<bool>,

    /// Whether to only capture identified users by default
    #[serde(skip_serializing_if = "Option::is_none")]
    pub default_identified_only: Option<bool>,

    /// Whether to capture dead clicks
    #[serde(skip_serializing_if = "Option::is_none")]
    pub capture_dead_clicks: Option<bool>,

    /// Error tracking configuration
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error_tracking: Option<ErrorTrackingConfig>,
}

#[derive(Debug, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ErrorTrackingConfig {
    pub autocapture_exceptions: bool,
    pub suppression_rules: Vec<Value>,
}

#[derive(Debug, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct FlagsResponse {
    pub errors_while_computing_flags: bool,
    pub flags: HashMap<String, FlagDetails>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub quota_limited: Option<Vec<String>>, // list of quota limited resources
    pub request_id: Uuid,

    #[serde(flatten)]
    pub config: ConfigResponse,
}

#[derive(Debug, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LegacyFlagsResponse {
    pub errors_while_computing_flags: bool,
    pub feature_flags: HashMap<String, FlagValue>,
    pub feature_flag_payloads: HashMap<String, Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub quota_limited: Option<Vec<String>>, // list of quota limited resources
    pub request_id: Uuid,

    #[serde(flatten)]
    pub config: ConfigResponse,
}

impl LegacyFlagsResponse {
    pub fn from_response(response: FlagsResponse) -> Self {
        Self {
            errors_while_computing_flags: response.errors_while_computing_flags,
            feature_flags: response
                .flags
                .iter()
                .map(|(key, flag)| (key.clone(), flag.to_value()))
                .collect(),
            feature_flag_payloads: response
                .flags
                .iter()
                .filter_map(|(key, flag)| {
                    flag.metadata
                        .payload
                        .clone()
                        .map(|payload| (key.clone(), payload))
                })
                .collect(),
            quota_limited: response.quota_limited,
            request_id: response.request_id,
            config: response.config,
        }
    }
}

/// Legacy decide v1 format response - returns just a list of active flag keys
#[derive(Debug, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DecideV1Response {
    pub feature_flags: Vec<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub quota_limited: Option<Vec<String>>,
    pub request_id: Uuid,

    #[serde(flatten)]
    pub config: ConfigResponse,
}

impl DecideV1Response {
    pub fn from_response(response: FlagsResponse) -> Self {
        // Only include flags that are enabled (active)
        let active_flags: Vec<String> = response
            .flags
            .iter()
            .filter(|(_, flag)| flag.enabled)
            .map(|(key, _)| key.clone())
            .collect();

        Self {
            feature_flags: active_flags,
            quota_limited: response.quota_limited,
            request_id: response.request_id,
            config: response.config,
        }
    }
}

/// Legacy decide v2 format response - returns active flags with their values
#[derive(Debug, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct DecideV2Response {
    pub feature_flags: HashMap<String, FlagValue>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub quota_limited: Option<Vec<String>>,
    pub request_id: Uuid,

    #[serde(flatten)]
    pub config: ConfigResponse,
}

impl DecideV2Response {
    pub fn from_response(response: FlagsResponse) -> Self {
        // Only include flags that are enabled
        let active_flags: HashMap<String, FlagValue> = response
            .flags
            .iter()
            .filter(|(_, flag)| flag.enabled)
            .map(|(key, flag)| (key.clone(), flag.to_value()))
            .collect();

        Self {
            feature_flags: active_flags,
            quota_limited: response.quota_limited,
            request_id: response.request_id,
            config: response.config,
        }
    }
}

impl FlagsResponse {
    pub fn new(
        errors_while_computing_flags: bool,
        flags: HashMap<String, FlagDetails>,
        quota_limited: Option<Vec<String>>,
        request_id: Uuid,
    ) -> Self {
        Self {
            errors_while_computing_flags,
            flags,
            quota_limited,
            request_id,
            config: ConfigResponse::default(),
        }
    }
}

#[derive(Debug, PartialEq, Eq, Deserialize, Serialize)]
pub struct FlagsOptionsResponse {
    pub status: FlagsResponseCode,
}

#[derive(Debug, PartialEq, Eq, Deserialize, Serialize)]
pub struct FlagDetails {
    pub key: String,
    pub enabled: bool,
    pub variant: Option<String>,
    pub reason: FlagEvaluationReason,
    pub metadata: FlagDetailsMetadata,
}

impl FlagDetails {
    pub fn to_value(&self) -> FlagValue {
        if let Some(variant) = &self.variant {
            FlagValue::String(variant.clone())
        } else {
            FlagValue::Boolean(self.enabled)
        }
    }
}

#[derive(Debug, PartialEq, Eq, Deserialize, Serialize)]
pub struct FlagDetailsMetadata {
    pub id: i32,
    pub version: i32,
    pub description: Option<String>,
    pub payload: Option<Value>,
}

#[derive(Clone, Debug, PartialEq, Eq, Deserialize, Serialize)]
pub struct FlagEvaluationReason {
    pub code: String,
    pub condition_index: Option<i32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
}

pub trait FromFeatureAndMatch {
    fn create(flag: &FeatureFlag, flag_match: &FeatureFlagMatch) -> Self;
    fn create_error(flag: &FeatureFlag, error_reason: &str, condition_index: Option<i32>) -> Self;
    fn get_reason_description(match_info: &FeatureFlagMatch) -> Option<String>;
}

impl FromFeatureAndMatch for FlagDetails {
    fn create(flag: &FeatureFlag, flag_match: &FeatureFlagMatch) -> Self {
        FlagDetails {
            key: flag.key.clone(),
            enabled: flag_match.matches,
            variant: flag_match.variant.clone(),
            reason: FlagEvaluationReason {
                code: flag_match.reason.to_string(),
                condition_index: flag_match.condition_index.map(|i| i as i32),
                description: Self::get_reason_description(flag_match),
            },
            metadata: FlagDetailsMetadata {
                id: flag.id,
                version: flag.version.unwrap_or(0),
                description: None,
                payload: flag_match.payload.clone(),
            },
        }
    }

    fn create_error(flag: &FeatureFlag, error_reason: &str, condition_index: Option<i32>) -> Self {
        FlagDetails {
            key: flag.key.clone(),
            enabled: false,
            variant: None,
            reason: FlagEvaluationReason {
                code: error_reason.to_string(),
                condition_index,
                description: None,
            },
            metadata: FlagDetailsMetadata {
                id: flag.id,
                version: flag.version.unwrap_or(0),
                description: None,
                payload: None,
            },
        }
    }

    fn get_reason_description(match_info: &FeatureFlagMatch) -> Option<String> {
        match match_info.reason {
            FeatureFlagMatchReason::ConditionMatch => {
                let set_number = match_info.condition_index.unwrap_or(0) + 1;
                Some(format!("Matched condition set {set_number}"))
            }
            FeatureFlagMatchReason::NoConditionMatch => {
                Some("No matching condition set".to_string())
            }
            FeatureFlagMatchReason::OutOfRolloutBound => Some("Out of rollout bound".to_string()),
            FeatureFlagMatchReason::NoGroupType => Some("No group type".to_string()),
            FeatureFlagMatchReason::SuperConditionValue => {
                Some("Super condition value".to_string())
            }
            FeatureFlagMatchReason::HoldoutConditionValue => {
                Some("Holdout condition value".to_string())
            }
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default, Eq)]
#[serde(rename_all = "camelCase")]
pub struct AnalyticsConfig {
    pub endpoint: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Default, Eq)]
#[serde(rename_all = "camelCase")]
pub struct SessionRecordingConfig {
    pub endpoint: Option<String>,
    pub console_log_recording_enabled: Option<bool>,
    pub recorder_version: Option<String>,
    pub sample_rate: Option<String>,
    pub minimum_duration_milliseconds: Option<i32>,
    pub linked_flag: Option<Value>, // string or object
    pub network_payload_capture: Option<Value>,
    pub masking: Option<Value>,
    pub url_triggers: Option<Value>,
    pub script_config: Option<Value>,
    pub url_blocklist: Option<Value>,
    pub event_triggers: Option<Value>,
    pub trigger_match_type: Option<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub record_canvas: Option<bool>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub canvas_fps: Option<u8>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub canvas_quality: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize, Eq)]
#[serde(untagged)]
pub enum SessionRecordingField {
    Disabled(bool), // NB: this should only ever be false
    Config(Box<SessionRecordingConfig>),
}

impl Default for SessionRecordingField {
    fn default() -> Self {
        SessionRecordingField::Disabled(false)
    }
}

/// Generic deserializer that treats empty strings as None for any type that implements FromStr
fn empty_string_as_none<'de, D, T>(de: D) -> Result<Option<T>, D::Error>
where
    D: Deserializer<'de>,
    T: FromStr,
    T::Err: fmt::Display,
{
    let opt = Option::<String>::deserialize(de)?;
    match opt.as_deref() {
        None | Some("") => Ok(None),
        Some(s) => FromStr::from_str(s).map_err(de::Error::custom).map(Some),
    }
}

/// Deserializer for timestamps that handles both strings and integers
fn deserialize_optional_timestamp<'de, D>(de: D) -> Result<Option<i64>, D::Error>
where
    D: Deserializer<'de>,
{
    #[derive(Deserialize)]
    #[serde(untagged)]
    enum IntOrString {
        Int(i64),
        String(String),
    }

    let opt = Option::<IntOrString>::deserialize(de)?;
    match opt {
        None => Ok(None),
        Some(IntOrString::Int(i)) => Ok(Some(i)),
        Some(IntOrString::String(s)) if s.is_empty() => Ok(None),
        Some(IntOrString::String(s)) => s.parse().map(Some).map_err(de::Error::custom),
    }
}

/// Deserializer for boolean query parameters that treats presence as true
/// Examples:
/// - `?config` → Some(true)
/// - `?config=` → Some(true)
/// - `?config=true` → Some(true)
/// - `?config=false` → Some(false)
/// - `?config=1` → Some(true)
/// - `?config=0` → Some(false)
/// - missing → None
fn deserialize_optional_bool<'de, D>(de: D) -> Result<Option<bool>, D::Error>
where
    D: Deserializer<'de>,
{
    #[derive(Deserialize)]
    #[serde(untagged)]
    enum BoolOrString {
        Bool(bool),
        String(String),
    }

    let opt = Option::<BoolOrString>::deserialize(de)?;
    match opt {
        None => Ok(None),
        Some(BoolOrString::Bool(b)) => Ok(Some(b)),
        Some(BoolOrString::String(s)) => {
            match s.to_lowercase().as_str() {
                "" => Ok(Some(true)), // Empty string = present = true
                "true" | "1" | "yes" | "on" => Ok(Some(true)),
                "false" | "0" | "no" | "off" => Ok(Some(false)),
                _ => Ok(Some(true)), // Any other value = true (presence indicates true)
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::flags::flag_match_reason::FeatureFlagMatchReason;
    use crate::flags::flag_matching::FeatureFlagMatch;
    use rstest::rstest;
    use serde_json::json;

    #[rstest]
    #[case::condition_match(
        FeatureFlagMatch {
            matches: true,
            variant: None,
            reason: FeatureFlagMatchReason::ConditionMatch,
            condition_index: Some(0),
            payload: None,
        },
        Some("Matched condition set 1".to_string())
    )]
    #[case::condition_match_different_set(
        FeatureFlagMatch {
            matches: true,
            variant: None,
            reason: FeatureFlagMatchReason::ConditionMatch,
            condition_index: Some(2),
            payload: None,
        },
        Some("Matched condition set 3".to_string())
    )]
    #[case::no_condition_match(
        FeatureFlagMatch {
            matches: false,
            variant: None,
            reason: FeatureFlagMatchReason::NoConditionMatch,
            condition_index: None,
            payload: None,
        },
        Some("No matching condition set".to_string())
    )]
    #[case::out_of_rollout(
        FeatureFlagMatch {
            matches: false,
            variant: None,
            reason: FeatureFlagMatchReason::OutOfRolloutBound,
            condition_index: Some(2),
            payload: None,
        },
        Some("Out of rollout bound".to_string())
    )]
    #[case::no_group_type(
        FeatureFlagMatch {
            matches: false,
            variant: None,
            reason: FeatureFlagMatchReason::NoGroupType,
            condition_index: None,
            payload: None,
        },
        Some("No group type".to_string())
    )]
    #[case::super_condition(
        FeatureFlagMatch {
            matches: true,
            variant: None,
            reason: FeatureFlagMatchReason::SuperConditionValue,
            condition_index: None,
            payload: None,
        },
        Some("Super condition value".to_string())
    )]
    #[case::holdout_condition(
        FeatureFlagMatch {
            matches: true,
            variant: None,
            reason: FeatureFlagMatchReason::HoldoutConditionValue,
            condition_index: None,
            payload: None,
        },
        Some("Holdout condition value".to_string())
    )]
    fn test_get_reason_description(
        #[case] flag_match: FeatureFlagMatch,
        #[case] expected_description: Option<String>,
    ) {
        assert_eq!(
            FlagDetails::get_reason_description(&flag_match),
            expected_description
        );
    }

    #[test]
    fn test_flags_response_only_includes_non_null_payloads() {
        // Create a response with multiple flags, some with payloads and some without
        let mut flags = HashMap::new();

        // Flag with payload
        flags.insert(
            "flag_with_payload".to_string(),
            FlagDetails {
                key: "flag_with_payload".to_string(),
                enabled: true,
                variant: None,
                reason: FlagEvaluationReason {
                    code: "condition_match".to_string(),
                    condition_index: Some(0),
                    description: None,
                },
                metadata: FlagDetailsMetadata {
                    id: 1,
                    version: 1,
                    description: None,
                    payload: Some(json!({"key": "value"})),
                },
            },
        );

        // Flag without payload
        flags.insert(
            "flag2".to_string(),
            FlagDetails {
                key: "flag2".to_string(),
                enabled: true,
                variant: None,
                reason: FlagEvaluationReason {
                    code: "condition_match".to_string(),
                    condition_index: Some(0),
                    description: None,
                },
                metadata: FlagDetailsMetadata {
                    id: 2,
                    version: 1,
                    description: None,
                    payload: None,
                },
            },
        );

        // Flag with null payload, which should not be filtered out; since Some(Value::Null) is not None
        flags.insert(
            "flag_with_null_payload".to_string(),
            FlagDetails {
                key: "flag_with_null_payload".to_string(),
                enabled: true,
                variant: None,
                reason: FlagEvaluationReason {
                    code: "condition_match".to_string(),
                    condition_index: Some(0),
                    description: None,
                },
                metadata: FlagDetailsMetadata {
                    id: 3,
                    version: 1,
                    description: None,
                    payload: Some(Value::Null),
                },
            },
        );

        let request_id = Uuid::new_v4();
        let response = FlagsResponse::new(false, flags, None, request_id);
        let legacy_response = LegacyFlagsResponse::from_response(response);

        // Check that only flag1 with actual payload is included
        assert_eq!(legacy_response.feature_flag_payloads.len(), 2);
        assert!(legacy_response
            .feature_flag_payloads
            .contains_key("flag_with_payload"));
        assert!(!legacy_response.feature_flag_payloads.contains_key("flag2"));
        assert!(legacy_response
            .feature_flag_payloads
            .contains_key("flag_with_null_payload"));

        // Verify the payload value
        assert_eq!(
            legacy_response
                .feature_flag_payloads
                .get("flag_with_payload"),
            Some(&json!({"key": "value"}))
        );
        assert_eq!(
            legacy_response
                .feature_flag_payloads
                .get("flag_with_null_payload"),
            Some(&json!(null))
        );

        // Check that the request_id is included
        assert_eq!(legacy_response.request_id, request_id);
    }

    #[test]
    fn test_config_fields_are_skipped_when_none() {
        let response = FlagsResponse::new(false, HashMap::new(), None, Uuid::new_v4());

        let json = serde_json::to_value(&response).unwrap();
        let obj = json.as_object().unwrap();

        // Config fields should not be present when None/empty
        assert!(!obj.contains_key("analytics"));
        assert!(!obj.contains_key("autocaptureExceptions"));
        assert!(!obj.contains_key("sessionRecording"));

        // Core fields should always be present
        assert!(obj.contains_key("errorsWhileComputingFlags"));
        assert!(obj.contains_key("flags"));
        assert!(obj.contains_key("requestId"));
    }

    #[test]
    fn test_config_fields_are_included_when_set() {
        let mut response = FlagsResponse::new(false, HashMap::new(), None, Uuid::new_v4());

        // Set some config fields
        response.config.analytics = Some(AnalyticsConfig {
            endpoint: Some("/analytics".to_string()),
        });
        response.config.supported_compression = vec!["gzip".to_string()];

        let json = serde_json::to_value(&response).unwrap();

        let obj = json.as_object().unwrap();

        // Config fields should be present when set
        assert!(obj.contains_key("analytics"));
        assert!(obj.contains_key("supportedCompression"));
    }
}
