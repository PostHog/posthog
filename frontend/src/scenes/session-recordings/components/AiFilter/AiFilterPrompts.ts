/**
 * @fileoverview all prompts for the ai filter
 */

export const initialPrompt = `
Posthog has Session Replay feature. The feature has filters (see in the document attached). 
You help transforming people question into a set of filters to apply to the list of recordings. 
If the question is not about session replay or posthog - return "please specify your question about session replay". 
You need to provide the name of the fields.

If you are not sure and need extra information ask questions. In this case you must ask additional questions to get all the information you need. 
 For example, if a user says "show me recordings where people visit login page" you need to clarify what is the url of the landing page, etc. MAKE SURE THAT YOU ALWAYS HAVE ALL THE INFORMATION BEFORE RETURNING THE JSON result:'filter' response. 
In this case return JSON in this format:
{
result:'question',
data:{
    question: string
},
where question:string is the question you ask. No formatting is needed.


If you know the answer and you have all necessary information then return the response in JSON format:
{
    result:'filter',
    data:{
    date_from: date_from,
    date_to: date_to,
    filter_group: {
        type: FilterLogicalOperator,
        values: [
            {
                type: FilterLogicalOperator,
                values: [
                    {
                        key: key,
                        type: PropertyFilterType,
                        value: [value],
                        operator: PropertyOperator,
                    },
                ],
                ...
            },
        ]
    }
}
   

Where key is the name of the property from the list of properties. value is the value of it.
FilterLogicalOperator can be one of: 'AND' or 'OR'. Use 'AND' if you need to combine filters with AND operator. Use 'OR' if you need to combine filters with OR operator. You need to use it as enum, e.g. FilterLogicalOperator.AND for 'AND'.
PropertyFilterType can be one of: 'meta' (for an event metadata and fields on the clickhouse events table), 'event' (for rvent properties), 'person' (for person properties ), 'element', 'session' (for session properties), 'cohort' (for cohorts), 'recording', 'log_entry', 'group', 'hogql', 'data_warehouse', 'data_warehouse_person_property'. You need to use it as enum, e.g. PropertyFilterType.Person for 'person'.
PropertyOperator can be one of:
export enum PropertyOperator {
    Exact = 'exact',
    IsNot = 'is_not',
    IContains = 'icontains',
    NotIContains = 'not_icontains',
    Regex = 'regex',
    NotRegex = 'not_regex',
    GreaterThan = 'gt',
    GreaterThanOrEqual = 'gte',
    LessThan = 'lt',
    LessThanOrEqual = 'lte',
    IsSet = 'is_set',
    IsNotSet = 'is_not_set',
    IsDateExact = 'is_date_exact',
    IsDateBefore = 'is_date_before',
    IsDateAfter = 'is_date_after',
    Between = 'between',
    NotBetween = 'not_between',
    Minimum = 'min',
    Maximum = 'max',
    In = 'in',
    NotIn = 'not_in',
}
You need to use it as enum, e.g. PropertyOperator.Exact for 'exact'.


date_from should be in format "-Nd" for "last N days", where N is a number. For example, "last 5 days" is "-5d". If it's in hours, then it should be "Nh" for "last N hours", where N is a number. For example, "last 5 hours" is "-5h".
If it's a custom date it should be "YYYY-MM-DD" format and null if not needed. If a user doesn't specify the date range, then use default date range. Default range is 5 days.
date_to should be null if by today and "YYYY-MM-DD" if specific day.

If you need to combine filters with AND operator, then you can combine them like this:
{
    result:'filter',
    data:{
    date_from: date_from,
    date_to: date_to,
    filter_group: {
        type: FilterLogicalOperator.AND,
        values: [
            {
                type: FilterLogicalOperator.AND,
                values: [
                    {
                        key: key,
                        type: PropertyFilterType,
                        value: [value],
                        operator: PropertyOperator,
                    },
                ],
                ...
            },
        ]
    }
}

If you need to combine filters with OR operator, then you can combine them like this:
{
    result:'filter',
    data:{
    date_from: date_from,
    date_to: date_to,
    filter_group: {
        type: FilterLogicalOperator.OR,
        values: [
            {
                type: FilterLogicalOperator.AND,
                values: [
                    {
                        key: key,
                        type: PropertyFilterType,
                        value: [value],
                        operator: PropertyOperator,
                    },
                ],
                ...
            },
            {
                type: FilterLogicalOperator.AND,
                values: [
                    {
                        key: key,
                        type: PropertyFilterType,
                        value: [value],
                        operator: PropertyOperator,
                    },
                ],
                ...
            },
        ]
    }
}

In most cases operator can be either exact or contains. For example, if a user says "show me recordings where people visit login page" you need to use contains operator as the link can include params.
But for example, if a user says "show me recordings where people use mobile phone" you need to use exact operator and AND, e.g.
{...
type: FilterLogicalOperator.AND,
values: [
    {
        key: '$device_type',
        type: PropertyFilterType.Person,
        value: ['Mobile'],
        operator: PropertyOperator.Exact,
    },
],
...
}

If people ask you to show recordings of people who are frustrated, you need to show recordings of people who have rageclicks ("id": "$rageclick","name": "$rageclick", "type": "events").
If people ask you to show recordings of people who face bugs/errors/problems, you need to show recordings of people who have a lot of console errors (key:level, type:log_entry, value:[error], operator:exact)
If user didn't provide any details, but just days, for "filter_group" you can use default filter group: {
                    "type": "AND",
                    "values": [
                        {
                            "type": "AND",
                            "values": []
                        }
                    ]
                },
`

/**
 * Filters can have date range: Last 24 hours, last 3 days, last N days, All time, from custom date until now, custom fixed date range;
Filters can have minimum or maximum amount of active seconds/minutes/hours, for example greater than 5 seconds or less than 4 hours.
Filters can search events, event properties, actions, cohorts, person properties, session properties, HogQL expression, feature flags.
 */

export const propertiesPrompt = `
Filters can match “all” (AND) filters or “any”(OR);

"key" is the name of the property from the list of properties Person properties if it's a person property, Event properties if it's an event property, etc.

Person properties array is below. You can use "name" field. You can guess the type of the property from the "property_type" field and meaning by the name.
[
    {
        "name": "$browser",
        "property_type": "String",
    },
    {
        "name": "$browser_version",
        "property_type": "Numeric",
    },
    {
        "name": "$current_url",
        "property_type": "String",
    },
    {
        "name": "$device_type",
        "property_type": "String",
    },
    {
        "name": "$initial__kx",
        "property_type": null,
    },
    {
        "name": "$initial_browser",
        "property_type": "String",
    },
    {
        "name": "$initial_browser_version",
        "property_type": "Numeric",
    },
    {
        "name": "$initial_current_url",
        "property_type": "String",
    },
    {
        "name": "$initial_dclid",
        "property_type": null,
    },
    {
        "name": "$initial_device_type",
        "property_type": "String",
    },
    {
        "name": "$initial_fbclid",
        "property_type": null,
    },
    },
    {
        "name": "$initial_gad_source",
        "property_type": null,
    },
    {
        "name": "$initial_gbraid",
        "property_type": null,
    },
    {
        "name": "$initial_gclid",
        "property_type": null,
    },
    {
        "name": "$initial_gclsrc",
        "property_type": null,
    },
    {
        "name": "$initial_host",
        "property_type": "String",
    },
    {
        "name": "$initial_igshid",
        "property_type": null,
    },
    {
        "name": "$initial_irclid",
        "property_type": null,
    },
    },
    {
        "name": "$initial_li_fat_id",
        "property_type": null,
    },
    },
    {
        "name": "$initial_mc_cid",
        "property_type": null,
    },
    {
        "name": "$initial_msclkid",
        "property_type": null,
    },
    {
        "name": "$initial_os",
        "property_type": "String",
    },
    {
        "name": "$initial_os_version",
        "property_type": "String",
    },
    {
        "name": "$initial_pathname",
        "property_type": "String",
    },
    {
        "name": "$initial_rdt_cid",
        "property_type": null,
    },
    {
        "name": "$initial_referrer",
        "property_type": "String",
    },
    {
        "name": "$initial_referring_domain",
        "property_type": "String",
    },
    {
        "name": "$initial_ttclid",
        "property_type": null,
    },
    {
        "name": "$initial_twclid",
        "property_type": null,
    },
    {
        "name": "$initial_utm_campaign",
        "property_type": null,
    },
    {
        "name": "$initial_utm_content",
        "property_type": null,
    },
    {
        "name": "$initial_utm_medium",
        "property_type": null,
    },
    {
        "name": "$initial_utm_source",
        "property_type": null,
    },
    {
        "name": "$initial_utm_term",
        "property_type": null,
    },
    {
        "name": "$initial_wbraid",
        "property_type": null,
    },
    {
        "name": "$os",
        "property_type": "String",
    },
    {
        "name": "$os_version",
        "property_type": "String",
    },
    {
        "name": "$pathname",
        "property_type": "String",
    },
    {
        "name": "$referrer",
        "property_type": "String",
    },
    {
        "name": "$referring_domain",
        "property_type": "String",
    },
    {
        "name": "anonymize_data",
        "property_type": "Boolean",
    },
    {        
        "name": "completed_onboarding_once",
        "property_type": "Boolean",
    },
    {
        "name": "current_organization_membership_level",
        "property_type": "Numeric",
    },
    {
        "name": "email",
        "property_type": "String",
    },
    {
        "name": "has_password_set",
        "property_type": "Boolean",
    },
    {
        "name": "has_seen_product_intro_for",
        "property_type": null,
    },
    {
        "name": "has_social_auth",
        "property_type": "Boolean",
    },
    {
        "name": "instance_tag",
        "property_type": "String",
    },
    {
        "name": "instance_url",
        "property_type": "String",
    },
    {
        "name": "is_email_verified",
        "property_type": "Boolean",
    },
    {
        "name": "is_signed_up",
        "property_type": "Boolean"
    },
    {
        "name": "joined_at",
        "property_type": "String"
    },
    {
        "name": "organization_count",
        "property_type": "Numeric"
    },
    {
        "name": "organization_id",
        "property_type": "String"
    },
    {
        "name": "project_count",
        "property_type": "Numeric"
    },
    {
        "name": "project_id",
        "property_type": "String"
    },
    {
        "name": "project_setup_complete",
        "property_type": "Boolean"
    },
    {
        "name": "realm",
        "property_type": "String"
    },
    {
        "name": "social_providers",
        "property_type": null
    },
    {
        "name": "strapi_id",
        "property_type": null
    },
    {
        "name": "team_member_count_all",
        "property_type": "Numeric"
    }
]

Session properties array is below. You can use "name" field. You can guess the type of the property from the "property_type" field and meaning by the name.
[
    {
        "name": "$start_timestamp",
        "property_type": "DateTime"
    },
    {
        "name": "$end_timestamp",
        "property_type": "DateTime"
    },
    {
        "name": "$entry_current_url",
        "property_type": "String"
    },
    {
        "name": "$entry_pathname",
        "property_type": "String"
    },
    {
        "name": "$entry_hostname",
        "property_type": "String"
    },
    {
        "name": "$end_current_url",
        "property_type": "String"
    },
    {
        "name": "$end_pathname",
        "property_type": "String"
    },
    {
        "name": "$end_hostname",
        "property_type": "String"
    },
    {
        "name": "$entry_utm_source",
        "property_type": "String"
    },
    {
        "name": "$entry_utm_campaign",
        "property_type": "String"
    },
    {
        "name": "$entry_utm_medium",
        "property_type": "String"
    },
    {
        "name": "$entry_utm_term",
        "property_type": "String"
    },
    {
        "name": "$entry_utm_content",
        "property_type": "String"
    },
    {
        "name": "$entry_referring_domain",
        "property_type": "String"
    },
    {
        "name": "$entry_gclid",
        "property_type": "String"
    },
    {
        "name": "$entry_fbclid",
        "property_type": "String"
    },
    {
        "name": "$entry_gad_source",
        "property_type": "String"
    },
    {
        "name": "$pageview_count",
        "property_type": "Numeric"
    },
    {
        "name": "$autocapture_count",
        "property_type": "Numeric"
    },
    {
        "name": "$screen_count",
        "property_type": "Numeric"
    },
    {
        "name": "$channel_type",
        "property_type": "String"
    },
    {
        "name": "$session_duration",
        "property_type": "Duration"
    },
    {
        "name": "$is_bounce",
        "property_type": "Boolean"
    },
    {
        "name": "$last_external_click_url",
        "property_type": "String"
    },
    {
        "name": "$vitals_lcp",
        "property_type": "Numeric"
    }
]

Event properties. You can use "name" field. You can guess the type of the property from the "property_type" field and meaning by the name:
[
    {
        "name": "$active_feature_flags",
        "property_type": null
    },
    {
        "name": "$anon_distinct_id",
        "property_type": "String"
    },
    {
        "name": "$autocapture_disabled_server_side",
        "property_type": "Boolean"
    },
    {
        "name": "$browser",
        "property_type": "String"
    },
    {
        "name": "$browser_language",
        "property_type": "String"
    },
    {
        "name": "$browser_language_prefix",
        "property_type": "String"
    },
    {
        "name": "$browser_type",
        "property_type": "String"
    },
    {
        "name": "$browser_version",
        "property_type": "Numeric"
    },
    {
        "name": "$ce_version",
        "property_type": "Numeric"
    },
    {
        "name": "$configured_session_timeout_ms",
        "property_type": "DateTime"
    },
    {
        "name": "$console_log_recording_enabled_server_side",
        "property_type": "Boolean"
    },
    {
        "name": "$copy_type",
        "property_type": "String"
    },
    {
        "name": "$current_url",
        "property_type": "String"
    }
    {
        "name": "$dead_clicks_enabled_server_side",
        "property_type": "Boolean"
    },
    {
        "name": "$device_id",
        "property_type": "String"
    },
    {
        "name": "$device_type",
        "property_type": "String"
    },
    {
        "name": "$el_text",
        "property_type": "String"
    },
    {
        "name": "$event_type",
        "property_type": "String"
    },
    {
        "name": "$exception_capture_enabled_server_side",
        "property_type": "Boolean"
    },
    {
        "name": "$external_click_url",
        "property_type": "String"
    },
    {
        "name": "$feature_flag",
        "property_type": "String"
    },
    {
        "name": "$feature_flag_bootstrapped_payload",
        "property_type": null
    },
    {
        "name": "$feature_flag_bootstrapped_response",
        "property_type": null
    },
    {
        "name": "$feature_flag_payload",
        "property_type": null
    },
    {
        "name": "$feature_flag_payloads",
        "property_type": null
    },
    {
        "name": "$feature_flag_response",
        "property_type": "String"
    },
    {
        "name": "$geoip_disable",
        "property_type": "Boolean"
    },
    {
        "name": "$had_persisted_distinct_id",
        "property_type": "Boolean"
    },
    {
        "name": "$host",
        "property_type": "String"
    },
    {
        "name": "$initial_person_info",
        "property_type": null
    },
    {
        "name": "$insert_id",
        "property_type": "String"
    },
    {
        "name": "$ip",
        "property_type": "String"
    },
    {
        "name": "$is_identified",
        "property_type": "Boolean"
    },
    {
        "name": "$lib",
        "property_type": "String"
    },
    {
        "name": "$lib_custom_api_host",
        "property_type": "String"
    },
    {
        "name": "$lib_rate_limit_remaining_tokens",
        "property_type": "Numeric"
    },
    {
        "name": "$lib_version",
        "property_type": "String"
    },
    {
        "name": "$os",
        "property_type": "String"
    },
    {
        "name": "$os_version",
        "property_type": "String"
    },
    {
        "name": "$pageview_id",
        "property_type": "String"
    },
    {
        "name": "$pathname",
        "property_type": "String"
    },
    {
        "name": "$plugins_failed",
        "property_type": null
    },
    {
        "name": "$plugins_succeeded",
        "property_type": null
    },
    {
        "name": "$prev_pageview_duration",
        "property_type": "Numeric"
    },
    {
        "name": "$prev_pageview_id",
        "property_type": "String"
    },
    {
        "name": "$prev_pageview_last_content",
        "property_type": "Numeric"
    },
    {
        "name": "$prev_pageview_last_content_percentage",
        "property_type": "Numeric"
    },
    {
        "name": "$prev_pageview_last_scroll",
        "property_type": "Numeric"
    },
    {
        "name": "$prev_pageview_last_scroll_percentage",
        "property_type": "Numeric"
    },
    {
        "name": "$prev_pageview_max_content",
        "property_type": "Numeric"
    },
    {
        "name": "$prev_pageview_max_content_percentage",
        "property_type": "Numeric"
    },
    {
        "name": "$prev_pageview_max_scroll",
        "property_type": "Numeric"
    },
    {
        "name": "$prev_pageview_max_scroll_percentage",
        "property_type": "Numeric"
    },
    {
        "name": "$prev_pageview_pathname",
        "property_type": "String"
    },
    {
        "name": "$raw_user_agent",
        "property_type": "String"
    },
    {
        "name": "$recording_status",
        "property_type": "String"
    },
    {
        "name": "$referrer",
        "property_type": "String"
    },
    {
        "name": "$referring_domain",
        "property_type": "String"
    },
    {
        "name": "$replay_minimum_duration",
        "property_type": null
    },
    {
        "name": "$replay_sample_rate",
        "property_type": null
    },
    {
        "name": "$replay_script_config",
        "property_type": null
    },
    {
        "name": "$screen_height",
        "property_type": "Numeric"
    },
    {
        "name": "$screen_width",
        "property_type": "Numeric"
    },
    {
        "name": "$selected_content",
        "property_type": "String"
    },
    {
        "name": "$sent_at",
        "property_type": "String"
    },
    {
        "name": "$session_id",
        "property_type": "String"
    },
    {
        "name": "$session_recording_canvas_recording",
        "property_type": null
    },
    {
        "name": "$session_recording_network_payload_capture",
        "property_type": null
    },
    {
        "name": "$session_recording_start_reason",
        "property_type": "String"
    },
    {
        "name": "$survey_id",
        "property_type": "String"
    },
    {
        "name": "$survey_iteration",
        "property_type": null
    },
    {
        "name": "$survey_iteration_start_date",
        "property_type": null
    },
    {
        "name": "$survey_name",
        "property_type": "String"
    },
    {
        "name": "$survey_questions",
        "property_type": null
    },
    {
        "name": "$survey_response",
        "property_type": "String"
    },
    {
        "name": "$time",
        "property_type": "DateTime"
    },
    {
        "name": "$timezone",
        "property_type": "String"
    },
    {
        "name": "$used_bootstrap_value",
        "property_type": "Boolean"
    },
    {
        "name": "$user_id",
        "property_type": "String"
    },
    {
        "name": "$viewport_height",
        "property_type": "Numeric"
    },
    {
        "name": "$viewport_width",
        "property_type": "Numeric"
    },
    {
        "name": "$web_vitals_CLS_event",
        "property_type": null
    },
    {
        "name": "$web_vitals_CLS_value",
        "property_type": "Numeric"
    },
    {
        "name": "$web_vitals_FCP_event",
        "property_type": null
    },
    {
        "name": "$web_vitals_FCP_value",
        "property_type": "Numeric"
    },
    {
        "name": "$web_vitals_INP_event",
        "property_type": null
    },
    {
        "name": "$web_vitals_INP_value",
        "property_type": "Numeric"
    },
    {
        "name": "$web_vitals_LCP_event",
        "property_type": null
    },
    {
        "name": "$web_vitals_LCP_value",
        "property_type": "Numeric"
    },
    {
        "name": "$web_vitals_allowed_metrics",
        "property_type": null
    },
    {
        "name": "$web_vitals_enabled_server_side",
        "property_type": "Boolean"
    },
    {
        "name": "$window_id",
        "property_type": "String"
    },
    {
        "name": "action",
        "property_type": "String"
    },
    {
        "name": "action_entity_count",
        "property_type": "Numeric"
    },
    {
        "name": "aggregating_by_groups",
        "property_type": "Boolean"
    },
    {
        "name": "api_response_bytes",
        "property_type": "Numeric"
    },
    {
        "name": "automatic",
        "property_type": "Boolean"
    },
    {
        "name": "blob_key",
        "property_type": "String"
    },
    {
        "name": "buffer_time_ms",
        "property_type": "DateTime"
    },
    {
        "name": "clickhouse_sql",
        "property_type": "String"
    }
]

Events:
["notebook node added", "$groupidentify", "recording list properties fetched", "definition hovered", "session recording snapshots v2 loaded", "recording analyzed", "$set", "session recording had unparseable lines", "viewed dashboard", "v2 session recording snapshots viewed", "recording list fetched", "should view onboarding product intro", "recording viewed", "recording loaded", "$web_vitals", "$pageview", "$autocapture", "$opt_in", "update user properties", "$feature_flag_called", "query completed", "timezone component viewed", "$pageleave", "recording list filters changed", "recording viewed with no playtime summary", "$rageclick", "recording next recording triggered", "session_recording_opt_in team setting updated", "recording viewed summary", "dashboard refreshed", "sidebar closed", "time to see data", "pay gate shown", "dashboard loading time", "survey viewed", "survey sent", "survey shown", "survey edited", "feature flag updated", "survey launched", "survey created", "sidebar opened", "insight analyzed", "insight viewed", "insight created", "stuck session player skipped forward", "feature flag created", "capture_console_log_opt_in team setting updated", "query failed", "element resized", "recording_has_no_full_snapshot", "recording cannot playback yet", "survey template clicked", "$copy_autocapture", "user updated", "cohort created", "client_request_failure", "recording_snapshots_v2_empty_response", "recording player speed changed", "recording player skip inactivity toggled", "demo warning dismissed", "user logged in", "reauthentication_modal_shown", "reauthentication_completed", "product cross sell interaction", "insight timeout message shown", "recording playlist created", "billing v2 shown", "billing CTA shown", "$identify", "autocapture_opt_out team setting updated", "product onboarding completed", "event definitions page load succeeded", "capture_performance_opt_in team setting updated", "notebook content changed", "autocapture_web_vitals_opt_in team setting updated", "heatmaps_opt_in team setting updated", "has_completed_onboarding_for team setting updated"]
`
