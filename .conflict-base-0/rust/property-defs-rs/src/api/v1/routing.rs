use crate::{
    api::v1::{constants::*, errors::ApiError, query::Manager},
    types::PropertyParentType,
    //metrics_consts::{},
    AppContext,
};

use anyhow::Result;
use axum::{
    extract::{Path, Query, State},
    routing::get,
    Json, Router,
};
use chrono::{DateTime, Utc};
use regex::Regex;
use serde::{Deserialize, Serialize};
use sqlx::{Execute, Executor, FromRow, Postgres, QueryBuilder, Row};
use tracing::debug;

use std::collections::{HashMap, HashSet};
use std::sync::Arc;

pub fn apply_routes(parent: Router, app_ctx: Arc<AppContext>) -> Router {
    let api_router = Router::new()
        .route(
            "/projects/:project_id/property_definitions",
            get(project_property_definitions_handler),
        )
        .with_state(app_ctx);

    parent.nest("/api/v1", api_router)
}

async fn project_property_definitions_handler(
    State(app_ctx): State<Arc<AppContext>>,
    Path(project_id): Path<i32>,
    Query(params): Query<HashMap<String, String>>,
) -> Result<Json<PropertyDefinitionResponse>, ApiError> {
    // parse and validate request's query params
    let params = parse_request(params);
    params.valid()?;
    debug!(
        "Request for project_id({}) w/params: {:?}",
        project_id, &params
    );

    let qmgr: &Manager = &app_ctx.query_manager;

    // construct the count query
    let mut count_bldr = QueryBuilder::<Postgres>::new("");
    let count_query = qmgr.count_query(&mut count_bldr, project_id, &params);
    let count_dbg: String = count_query.sql().into();
    debug!("Count query: {:?}", &count_dbg);

    // construct the property definitions query
    let mut props_bldr = QueryBuilder::<Postgres>::new("");
    let props_query = qmgr.property_definitions_query(&mut props_bldr, project_id, &params);
    let props_dbg: String = props_query.sql().into();
    debug!("Prop defs query: {:?}", &props_dbg);

    let total_count: i64 = match qmgr.pool.fetch_one(count_query).await {
        Ok(row) => row.get(0),
        Err(e) => return Err(ApiError::QueryError(format!("executing count query: {e}"))),
    };

    let mut prop_defs: Vec<PropertyDefinition> = vec![];
    match qmgr.pool.fetch_all(props_query).await {
        Ok(result) => {
            for row in result {
                let pd = PropertyDefinition::from_row(&row).map_err(|e| {
                    ApiError::QueryError(format!("deserializing prop defs row: {e}"))
                })?;
                prop_defs.push(pd);
            }
        }
        Err(e) => {
            return Err(ApiError::QueryError(format!(
                "executing prop defs query: {e}"
            )))
        }
    }

    // build and return JSON response
    Ok(Json(PropertyDefinitionResponse {
        count: total_count,
        results: prop_defs,
    }))
}

fn parse_request(params: HashMap<String, String>) -> Params {
    // which category of properties do we filter for? default is "event"
    let parent_type = params
        .get("type")
        .map_or(PropertyParentType::Event, |s| match s.as_str() {
            "event" => PropertyParentType::Event,
            "person" => PropertyParentType::Person,
            "group" => PropertyParentType::Group,
            "session" => PropertyParentType::Session,
            _ => PropertyParentType::Event,
        });

    // search terms: optional - each term is a fragment that will be
    // fuzzy-searched in Postgres against the specified search fields
    // DIVERGES FROM DJANGO API: the new Rust API will accept lists as space-separated query param values
    let search_terms_filter = Regex::new(r"^[ a-z0-9$._-]+$").unwrap();
    let search_terms: Vec<String> = params
        .get("search")
        .filter(|s| search_terms_filter.is_match(s))
        .map(|raw| {
            raw.split(" ")
                .map(|s| s.trim().to_lowercase().to_string())
                .collect()
        })
        .unwrap_or_default();

    // refine search fields if "latest" keyword is present in search terms
    let filter_initial_props = parent_type == PropertyParentType::Person
        && search_terms
            .iter()
            .any(|st| st.as_str() == SEARCH_TRIGGER_WORD);

    // which columns should we fuzzy-search for each of the user-supplied search terms?
    // defaults to "posthog_propertydefinition.name" column, but user can supply more
    // DIVERGES FROM DJANGO API: the new Rust API will accept lists as space-separated query param values
    let mut search_fields: HashSet<String> = HashSet::from(["name".to_string()]);
    let sf_overrides: Vec<String> = params
        .get("search_fields")
        .map(|raw| {
            raw.split(" ")
                .map(|s| s.trim().to_lowercase().to_string())
                .collect()
        })
        .unwrap_or_default();
    for field in sf_overrides {
        if !field.is_empty() {
            search_fields.insert(field);
        }
    }

    // defaults to "-1" if the caller didn't supply the group_type_index, or the parent_type != "group"
    let group_type_index: i32 = params.get("group_type_index").map_or(-1, |s| {
        s.parse::<i32>().ok().map_or(-1, |gti| {
            if parent_type == PropertyParentType::Group {
                // group_type_index value on "group" type query is validated downstream
                gti
            } else {
                -1
            }
        })
    });

    // DIVERGES FROM DJANGO API: the new Rust API will accept lists as space-separated query param values
    let properties: Vec<String> = params
        .get("properties")
        .map(|raw| raw.split(" ").map(|s| s.trim().to_string()).collect())
        .unwrap_or_default();

    let is_numerical = params
        .get("is_numerical")
        .and_then(|s| s.parse::<bool>().ok())
        .unwrap_or(false);

    // false is not equivalent of absence here so make this an Option
    let is_feature_flag = params
        .get("is_feature_flag")
        .and_then(|s| s.parse::<bool>().ok());

    // DIVERGES FROM DJANGO API: the new Rust API will accept lists as space-separated query param values
    let excluded_properties = params
        .get("excluded_properties")
        .map(|raw| raw.split(" ").map(|s| s.trim().to_string()).collect())
        .unwrap_or_default();

    // NOTE: this is calculated using the User model in the Django app, so probably easiest to
    // to just pass the result of those checks from the caller (Django) to this API? the flag decides
    // if the props def query should join in enterprise prop defs and (indirectly) the users table.
    // defaulting to true for now, but TBD if this is in parity w/original yet. see also:
    // https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L463
    // https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L504-L508
    let use_enterprise_taxonomy = params
        .get("use_enterprise_taxonomy")
        .and_then(|s| s.parse::<bool>().ok())
        .unwrap_or(true);

    // DIVERGES FROM DJANGO API: the new Rust API will accept lists as space-separated query param values
    // https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L214
    let event_names = params
        .get("event_names")
        .map(|raw| raw.split(" ").map(|s| s.trim().to_string()).collect())
        .unwrap_or_default();

    let limit: i64 = params.get("limit").map_or(DEFAULT_QUERY_LIMIT, |s| {
        s.parse::<i64>().unwrap_or(DEFAULT_QUERY_LIMIT)
    });

    let offset: i64 = params.get("offset").map_or(DEFAULT_QUERY_OFFSET, |s| {
        s.parse::<i64>().unwrap_or(DEFAULT_QUERY_OFFSET)
    });

    Params {
        search_terms,
        search_fields,
        parent_type,
        group_type_index,
        properties,
        excluded_properties,
        event_names,
        is_feature_flag,
        is_numerical,
        use_enterprise_taxonomy,
        filter_initial_props,
        limit,
        offset,
    }
}

#[derive(Debug)]
pub struct Params {
    pub search_terms: Vec<String>,
    pub search_fields: HashSet<String>,
    pub parent_type: PropertyParentType,
    pub group_type_index: i32,
    pub properties: Vec<String>,
    pub excluded_properties: Vec<String>,
    pub event_names: Vec<String>,
    pub is_feature_flag: Option<bool>,
    pub is_numerical: bool,
    pub use_enterprise_taxonomy: bool,
    pub filter_initial_props: bool,
    pub limit: i64,
    pub offset: i64,
}

impl Params {
    // https://github.com/PostHog/posthog/blob/master/posthog/taxonomy/property_definition_api.py#L81-L96
    pub fn valid(&self) -> Result<(), ApiError> {
        if self.parent_type == PropertyParentType::Group
            && !(0..GROUP_TYPE_LIMIT).contains(&self.group_type_index)
        {
            return Err(ApiError::InvalidRequestParam(
                "property_type 'group' requires valid 'group_type_index' parameter".to_string(),
            ));
        }

        if self.parent_type != PropertyParentType::Group && self.group_type_index != -1 {
            return Err(ApiError::InvalidRequestParam(
                "parameter 'group_type_index' is only allowed with property_type 'group'"
                    .to_string(),
            ));
        }

        if !self.event_names.is_empty() && self.parent_type != PropertyParentType::Event {
            return Err(ApiError::InvalidRequestParam(
                "parameter 'event_names' is only allowed with property_type 'event'".to_string(),
            ));
        }

        Ok(())
    }
}

impl Default for Params {
    fn default() -> Self {
        Params {
            search_terms: vec![],
            search_fields: HashSet::from(["name".to_string()]),
            parent_type: PropertyParentType::Event,
            group_type_index: -1,
            properties: vec![],
            excluded_properties: vec![],
            event_names: vec![],
            is_feature_flag: None,
            is_numerical: false,
            use_enterprise_taxonomy: true,
            filter_initial_props: false,
            limit: 100,
            offset: 0,
        }
    }
}

//
// JSON API response structures below. These are shaped as the original Django API does
//

#[derive(Serialize)]
pub struct PropertyDefinitionResponse {
    count: i64,
    results: Vec<PropertyDefinition>,
    // let the caller (Django monolith) handle pagination and next/prev URI building
}

#[derive(Serialize, Deserialize, FromRow)]
pub struct PropertyDefinition {
    id: uuid::Uuid,
    name: String,
    property_type: Option<String>,
    is_numerical: Option<bool>,
    is_seen_on_filtered_events: Option<bool>,
    updated_at: Option<DateTime<Utc>>,
    updated_by_id: Option<i64>,
    verified: Option<bool>,
    verified_at: Option<DateTime<Utc>>,
    verified_by_id: Option<i64>,
    tags: Option<Vec<String>>,
}
