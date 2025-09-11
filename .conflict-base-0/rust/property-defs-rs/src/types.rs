use std::{fmt, hash::Hash, str::FromStr, sync::LazyLock};

use chrono::{DateTime, Duration, DurationRound, RoundingError, Utc};
use regex::Regex;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use sqlx::{Executor, Postgres};
use tracing::warn;
use uuid::Uuid;

use crate::metrics_consts::{EVENTS_SKIPPED, UPDATES_ISSUED, UPDATES_SKIPPED};

// We skip updates for events we generate
pub const EVENTS_WITHOUT_PROPERTIES: [&str; 1] = ["$$plugin_metrics"];

pub const SIX_MONTHS_AGO_SECS: u64 = 15768000;
// These properties have special meaning, and are ignored
pub const SKIP_PROPERTIES: [&str; 9] = [
    "$set",
    "$set_once",
    "$unset",
    "$group_0",
    "$group_1",
    "$group_2",
    "$group_3",
    "$group_4",
    "$groups",
];

const DATETIME_PROPERTY_NAME_KEYWORDS: [&str; 7] = [
    "time",
    "timestamp",
    "date",
    "_at",
    "-at",
    "createdat",
    "updatedat",
];

// TRICKY: the pattern below is a best-effort attempt to classify likely DateTime properties by
// a string prefix of their value. While this doesn't enforce compliance to standard formats,
// it does represent a pretty strong indication of the user's intent, for the purposes of
// *property definition capture only* especially when a bad decision "locks" the property name
// to the wrong type. Try it here: https://rustexp.lpil.uk/ and review the unit tests.
// Also notable: post-capture, PostHog displays timestamps in a variety formats:
// https://github.com/PostHog/posthog/blob/master/posthog/models/property_definition.py#L18-L30
static DATETIME_PREFIX_REGEX: LazyLock<Regex> = LazyLock::new(|| {
    regex::Regex::new(
        r#"^(([0-9]{4}[/-][0-2][0-9][/-][0-3][0-9])|([0-2][0-9][/-][0-3][0-9][/-][0-9]{4}))([ T][0-2][0-9]:[0-6][0-9]:[0-6][0-9].*)?$"#
    ).unwrap()
});

#[derive(Clone, Copy, Debug, Eq, PartialEq, Hash, PartialOrd, Ord)]
pub enum PropertyParentType {
    Event = 1,
    Person = 2,
    Group = 3,
    Session = 4,
}

impl From<PropertyParentType> for i32 {
    fn from(parent_type: PropertyParentType) -> i32 {
        match parent_type {
            PropertyParentType::Event => 1,
            PropertyParentType::Person => 2,
            PropertyParentType::Group => 3,
            PropertyParentType::Session => 4,
        }
    }
}

#[derive(Clone, Debug, Deserialize, Serialize, Eq, PartialEq, PartialOrd, Ord)]
pub enum PropertyValueType {
    DateTime,
    String,
    Numeric,
    Boolean,
    Duration, // Unused, but exists.
}

impl fmt::Display for PropertyValueType {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        match self {
            PropertyValueType::DateTime => write!(f, "DateTime"),
            PropertyValueType::String => write!(f, "String"),
            PropertyValueType::Numeric => write!(f, "Numeric"),
            PropertyValueType::Boolean => write!(f, "Boolean"),
            PropertyValueType::Duration => write!(f, "Duration"),
        }
    }
}

// The grouptypemapping table uses i32's, but we get group types by name, so we have to resolve them before DB writes, sigh
#[derive(Clone, Debug, Eq, PartialEq, PartialOrd, Ord)]
pub enum GroupType {
    Unresolved(String),
    Resolved(String, i32),
}

impl GroupType {
    pub fn resolve(self, index: i32) -> Self {
        match self {
            GroupType::Unresolved(name) => GroupType::Resolved(name, index),
            GroupType::Resolved(name, _) => GroupType::Resolved(name, index),
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, PartialOrd, Ord)]
pub struct PropertyDefinition {
    pub team_id: i32,
    pub project_id: i64,
    pub name: String,
    pub is_numerical: bool,
    pub property_type: Option<PropertyValueType>,
    pub event_type: PropertyParentType,
    pub group_type_index: Option<GroupType>,
    pub property_type_format: Option<String>, // Deprecated
    pub volume_30_day: Option<i64>,           // Deprecated
    pub query_usage_30_day: Option<i64>,      // Deprecated
}

#[derive(Clone, Debug, Eq, PartialEq, PartialOrd, Ord)]
pub struct EventDefinition {
    pub name: String,
    pub team_id: i32,
    pub project_id: i64,
    pub last_seen_at: DateTime<Utc>, // Always floored to our update rate for last_seen, so this Eq derive is safe for deduping
}

// Derived hash since these are keyed on all fields in the DB
#[derive(Clone, Debug, Hash, Eq, PartialEq, PartialOrd, Ord)]
pub struct EventProperty {
    pub team_id: i32,
    pub project_id: i64,
    pub event: String,
    pub property: String,
}

// Represents a generic update, but comparable, allowing us to dedupe and cache updates
#[derive(Clone, Debug, Hash, Eq, PartialEq, PartialOrd, Ord)]
pub enum Update {
    Event(EventDefinition),
    Property(PropertyDefinition),
    EventProperty(EventProperty),
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Event {
    pub team_id: i32,
    pub project_id: i64,
    pub event: String,
    pub properties: Option<String>,
}

impl From<&Event> for EventDefinition {
    fn from(event: &Event) -> Self {
        EventDefinition {
            name: sanitize_string(&event.event),
            team_id: event.team_id,
            project_id: event.project_id,
            last_seen_at: get_floored_last_seen(),
        }
    }
}

impl Event {
    pub fn into_updates(self, skip_threshold: usize) -> Vec<Update> {
        if EVENTS_WITHOUT_PROPERTIES.contains(&self.event.as_str()) {
            metrics::counter!(EVENTS_SKIPPED, &[("reason", "no_properties_event")]).increment(1);
            return vec![];
        }

        if !will_fit_in_postgres_column(&self.event) {
            metrics::counter!(EVENTS_SKIPPED, &[("reason", "name_wont_fit_in_postgres")])
                .increment(1);
            return vec![];
        }

        let team_id = self.team_id;
        let event = self.event.clone();

        let updates = self.into_updates_inner();
        if updates.len() > skip_threshold {
            warn!(
                "Event {} for team {} has more than {} properties, skipping",
                event, team_id, skip_threshold
            );
            metrics::counter!(EVENTS_SKIPPED, &[("reason", "too_many_properties")]).increment(1);
            return vec![];
        }

        updates
    }

    fn into_updates_inner(self) -> Vec<Update> {
        let mut updates = vec![Update::Event(EventDefinition::from(&self))];
        let Some(props) = &self.properties else {
            return updates;
        };

        let Ok(props) = Value::from_str(props) else {
            return updates;
        };

        let Value::Object(props) = props else {
            return updates;
        };

        // If this is a groupidentify event, we ONLY bubble up the group properties
        if self.event == "$groupidentify" {
            let Some(Value::String(group_type)) = props.get("$group_type") else {
                return updates;
            };
            let group_type = GroupType::Unresolved(group_type.clone());

            let Some(group_properties) = props.get("$group_set") else {
                return updates;
            };

            let Value::Object(group_properties) = group_properties else {
                return updates;
            };

            self.get_props_from_object(
                &mut updates,
                group_properties,
                PropertyParentType::Group,
                Some(group_type),
            );
            return updates;
        }

        // Grab the "ordinary" (non-person) event properties
        self.get_props_from_object(&mut updates, &props, PropertyParentType::Event, None);

        // If there are any person properties, also push those into the flat property map.
        if let Some(Value::Object(set_props)) = props.get("$set") {
            self.get_props_from_object(&mut updates, set_props, PropertyParentType::Person, None)
        }
        if let Some(Value::Object(set_once_props)) = props.get("$set_once") {
            self.get_props_from_object(
                &mut updates,
                set_once_props,
                PropertyParentType::Person,
                None,
            )
        }

        updates
    }

    fn get_props_from_object(
        &self,
        updates: &mut Vec<Update>,
        set: &Map<String, Value>,
        parent_type: PropertyParentType,
        group_type: Option<GroupType>,
    ) {
        updates.reserve(set.len() * 2);
        for (key, value) in set {
            if SKIP_PROPERTIES.contains(&key.as_str()) && parent_type == PropertyParentType::Event {
                continue;
            }

            if !will_fit_in_postgres_column(key) {
                metrics::counter!(
                    UPDATES_SKIPPED,
                    &[("reason", "property_name_wont_fit_in_postgres")]
                )
                .increment(2); // We're skipping one EventProperty, and one PropertyDefinition
                continue;
            }

            updates.push(Update::EventProperty(EventProperty {
                team_id: self.team_id,
                project_id: self.project_id,
                event: sanitize_string(&self.event),
                property: key.clone(),
            }));

            let property_type = detect_property_type(key, value);
            let is_numerical = matches!(property_type, Some(PropertyValueType::Numeric));

            updates.push(Update::Property(PropertyDefinition {
                team_id: self.team_id,
                project_id: self.project_id,
                name: key.clone(),
                is_numerical,
                property_type,
                event_type: parent_type,
                group_type_index: group_type.clone(),
                property_type_format: None,
                volume_30_day: None,
                query_usage_30_day: None,
            }));
        }
    }
}

pub fn detect_property_type(key: &str, value: &Value) -> Option<PropertyValueType> {
    let key = key.to_lowercase();

    // There are a whole set of special cases here, taken from the TS
    if key.starts_with("utm_") {
        // utm_ prefixed properties should always be detected as strings.
        // Sometimes the first value sent looks like a number, event though
        // subsequent values are not. See
        // https://github.com/PostHog/posthog/issues/12529 for more context.
        return Some(PropertyValueType::String);
    }
    if key.starts_with("$feature/") {
        // $feature/ prefixed properties should always be detected as strings.
        // These are feature flag values, and can be boolean or string.
        // Sometimes the first value sent is boolean (because flag isn't enabled) while
        // subsequent values are not. We don't want this to be misunderstood as a boolean.
        return Some(PropertyValueType::String);
    }

    if key == "$feature_flag_response" {
        // $feature_flag_response properties should always be detected as strings.
        // These are feature flag values, and can be boolean or string.
        // Sometimes the first value sent is boolean (because flag isn't enabled) while
        // subsequent values are not. We don't want this to be misunderstood as a boolean.
        return Some(PropertyValueType::String);
    }

    if key.starts_with("$survey_response") {
        // NB: $survey_responses are collected in an interesting way, where the first
        // response is called `$survey_response` and subsequent responses are called
        // `$survey_response_2`, `$survey_response_3`, etc.  So, this check should auto-cast
        // all survey responses to strings, and $survey_response properties should always be detected as strings.
        return Some(PropertyValueType::String);
    }

    if detect_timestamp_property_by_key_and_value(&key, value) {
        return Some(PropertyValueType::DateTime);
    }

    // OK, attempt to classify prop type on value alone
    match value {
        Value::String(s) => {
            let s = &s.trim();
            if *s == "true" || *s == "false" || *s == "TRUE" || *s == "FALSE" {
                Some(PropertyValueType::Boolean)
            // Try to parse this as an ISO 8601 date, and if we can, use that as the type instead
            } else if is_likely_date_string(s) {
                Some(PropertyValueType::DateTime)
            } else {
                Some(PropertyValueType::String)
            }
        }

        Value::Number(_) => Some(PropertyValueType::Numeric),

        Value::Bool(_) => Some(PropertyValueType::Boolean),

        _ => None,
    }
}

fn detect_timestamp_property_by_key_and_value(key: &str, value: &Value) -> bool {
    if DATETIME_PROPERTY_NAME_KEYWORDS
        .iter()
        .any(|kw| key.contains(*kw))
    {
        return match value {
            Value::String(s) if is_likely_date_string(s) => true,
            Value::Number(n) if is_likely_unix_timestamp(n) => true,
            _ => false,
        };
    }

    false
}

fn is_likely_date_string(s: &str) -> bool {
    if DateTime::parse_from_rfc3339(s).is_ok() || DateTime::parse_from_rfc2822(s).is_ok() {
        return true;
    }

    if DATETIME_PREFIX_REGEX.is_match(s) {
        return true;
    }

    false
}

// frought with peril if folks are pushing big(ish) numbers into event prop values...
fn is_likely_unix_timestamp(n: &serde_json::Number) -> bool {
    if let Some(value) = n.as_u64() {
        // we could go more conservative here, but you get the idea
        let threshold: u64 = (Utc::now().timestamp_millis() as u64 / 1000u64) - SIX_MONTHS_AGO_SECS;
        if value >= threshold {
            return true;
        }
    }

    false
}

// These hash impls correspond to DB uniqueness constraints, pulled from the TS
impl Hash for PropertyDefinition {
    fn hash<H: std::hash::Hasher>(&self, state: &mut H) {
        self.team_id.hash(state);
        self.name.hash(state);
        self.event_type.hash(state);
        self.group_type_index.hash(state);
    }
}

impl Hash for EventDefinition {
    fn hash<H: std::hash::Hasher>(&self, state: &mut H) {
        self.team_id.hash(state);
        self.name.hash(state);
        self.last_seen_at.hash(state)
    }
}

// Ensure group type hashes identically regardless of whether it's resolved or not. Note that if
// someone changes the name associated with a group type, all subsequent events will hash differently
// because of this, but that seems fine - it just means a few extra DB ops issued, we index on the i32
// at write time anyway
impl Hash for GroupType {
    fn hash<H: std::hash::Hasher>(&self, state: &mut H) {
        match self {
            GroupType::Unresolved(name) => name.hash(state),
            GroupType::Resolved(name, _) => name.hash(state),
        }
    }
}

// We round last seen to the nearest hour. Unwrap is safe here because
// the duration is positive, non-zero, and smaller than time since epoch
pub fn get_floored_last_seen() -> DateTime<Utc> {
    floor_datetime(Utc::now(), Duration::hours(1)).unwrap()
}

fn floor_datetime(dt: DateTime<Utc>, duration: Duration) -> Result<DateTime<Utc>, RoundingError> {
    let rounded = dt.duration_round(duration)?;

    // If we rounded up
    if rounded > dt {
        Ok(rounded - duration)
    } else {
        Ok(rounded)
    }
}

// We impose some limits on some fields for legacy reasons, and drop updates that don't conform to them
pub const DJANGO_MAX_CHARFIELD_LENGTH: usize = 400;
fn will_fit_in_postgres_column(str: &str) -> bool {
    str.len() <= DJANGO_MAX_CHARFIELD_LENGTH / 2
}

// Postgres doesn't like nulls in strings, so we replace them with uFFFD.
// This allocates, so only do it right when hitting the DB. We handle nulls
// in strings just fine.
pub fn sanitize_string(s: &str) -> String {
    s.replace('\u{0000}', "\u{FFFD}")
}

// The queries below are pulled more-or-less exactly from the TS impl.

impl EventDefinition {
    pub async fn issue<'c, E>(&self, executor: E) -> Result<(), sqlx::Error>
    where
        E: Executor<'c, Database = Postgres>,
    {
        let res = sqlx::query!(
            r#"
            INSERT INTO posthog_eventdefinition (id, name, volume_30_day, query_usage_30_day, team_id, project_id, last_seen_at, created_at)
            VALUES ($1, $2, NULL, NULL, $3, $4, $5, NOW())
            ON CONFLICT (coalesce(project_id, team_id::bigint), name)
            DO UPDATE SET last_seen_at = $5
        "#,
            Uuid::now_v7(),
            self.name,
            self.team_id,
            self.project_id,
            Utc::now() // We floor the update datetime to the nearest day for cache purposes, but can insert the exact time we see the event
        ).execute(executor).await.map(|_| ());

        metrics::counter!(UPDATES_ISSUED, &[("type", "event_definition")]).increment(1);

        res
    }
}
