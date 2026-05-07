DROP VIEW IF EXISTS raw_sessions_v3_v

DROP TABLE IF EXISTS raw_sessions_v3

DROP TABLE IF EXISTS writable_raw_sessions_v3

DROP TABLE IF EXISTS sharded_raw_sessions_v3 SYNC

CREATE TABLE IF NOT EXISTS sharded_raw_sessions_v3
(
    team_id Int64,

    -- Both UInt128 and UUID are imperfect choices here
    -- see https://michcioperz.com/wiki/clickhouse-uuid-ordering/
    -- but also see https://github.com/ClickHouse/ClickHouse/issues/77226 and hope
    -- right now choose UInt128 as that's the type of events.$session_id_uuid, but in the future we will probably want to switch everything to the new CH UUID type (when it's released)
    session_id_v7 UInt128,
    -- Ideally we would not need to store this separately, as the ID *is* the timestamp
    -- Unfortunately for now, chaining clickhouse functions to extract the timestamp will break indexes / partition pruning, so do this workaround
    -- again, when the new CH UUID type is released, we should try to switch to that and remove the separate timestamp column
    session_timestamp DateTime64 DEFAULT fromUnixTimestamp64Milli(toUInt64(bitShiftRight(session_id_v7, 80))),

    -- ClickHouse will pick the latest value of distinct_id for the session
    -- this is fine since even if the distinct_id changes during a session
    -- it will still (or should still) map to the same person
    distinct_id AggregateFunction(argMax, String, DateTime64(6, 'UTC')),
    distinct_ids AggregateFunction(groupUniqArray, String),

    min_timestamp SimpleAggregateFunction(min, DateTime64(6, 'UTC')),
    max_timestamp SimpleAggregateFunction(max, DateTime64(6, 'UTC')),
    max_inserted_at SimpleAggregateFunction(max, DateTime64(6, 'UTC')),

    -- urls
    urls SimpleAggregateFunction(groupUniqArrayArray(2000), Array(String)),
    entry_url AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    end_url AggregateFunction(argMax, Nullable(String), DateTime64(6, 'UTC')),
    last_external_click_url AggregateFunction(argMax, Nullable(String), DateTime64(6, 'UTC')),

    -- device
    browser AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    browser_version AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    os AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    os_version AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    device_type AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    viewport_width AggregateFunction(argMin, Nullable(Int64), DateTime64(6, 'UTC')),
    viewport_height AggregateFunction(argMin, Nullable(Int64), DateTime64(6, 'UTC')),

    -- geoip
    -- only store the properties we actually use, as there's tons, see https://posthog.com/docs/cdp/geoip-enrichment
    geoip_country_code AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    geoip_subdivision_1_code AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    geoip_subdivision_1_name AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    geoip_subdivision_city_name AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    geoip_time_zone AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),

    -- attribution
    entry_referring_domain AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    entry_utm_source AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    entry_utm_campaign AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    entry_utm_medium AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    entry_utm_term AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    entry_utm_content AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    entry_gclid AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    entry_gad_source AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    entry_fbclid AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),

    -- for channel type calculation, it's enough to know if these were present
    entry_has_gclid AggregateFunction(argMin, Boolean, DateTime64(6, 'UTC')),
    entry_has_fbclid AggregateFunction(argMin, Boolean, DateTime64(6, 'UTC')),

    -- for lower-tier ad ids, just put them in a map, and set of the ones present
    entry_ad_ids_map AggregateFunction(argMin, Map(String, String), DateTime64(6, 'UTC')),
    entry_ad_ids_set AggregateFunction(argMin, Array(String), DateTime64(6, 'UTC')),

    -- channel type properties tuple - to reduce redundant reading of the timestamp when loading all of these columns
    -- utm_source, utm_medium, utm_campaign, referring domain, has_gclid, has_fbclid, gad_source
    entry_channel_type_properties AggregateFunction(argMin, Tuple(Nullable(String), Nullable(String), Nullable(String), Nullable(String), Boolean, Boolean, Nullable(String)), DateTime64(6, 'UTC')),

    -- Count pageview, autocapture, and screen events for providing totals.
    -- Use uniqExact instead of count, so that inserting events can be idempotent. This is necessary as sometimes we see
    -- events being inserted multiple times to be deduped later, but that can trigger multiple rows here.
    -- Additionally, idempotency is useful for backfilling, as we can just reinsert the same events without worrying.
    pageview_uniq AggregateFunction(uniqExact, Nullable(UUID)),
    autocapture_uniq AggregateFunction(uniqExact, Nullable(UUID)),
    screen_uniq AggregateFunction(uniqExact, Nullable(UUID)),

    -- As a performance optimisation, also keep track of the uniq events for all of these combined.
    -- This is a much more efficient way of calculating the bounce rate, as >2 means not a bounce
    page_screen_uniq_up_to AggregateFunction(uniqUpTo(1), Nullable(UUID)),
    has_autocapture SimpleAggregateFunction(max, Boolean),

    -- Flags - store every seen value for each flag
    flag_values AggregateFunction(groupUniqArrayMap, Map(String, String)),
    flag_keys SimpleAggregateFunction(groupUniqArrayArray, Array(String)),

    -- Event names - store unique event names seen in this session
    event_names SimpleAggregateFunction(groupUniqArrayArray(2000), Array(String)),

    -- Hosts - store unique hostnames seen in this session (extracted from $host property)
    hosts SimpleAggregateFunction(groupUniqArrayArray(100), Array(String)),

    -- Emails - store unique emails seen in this session (extracted from person_properties.email)
    emails SimpleAggregateFunction(groupUniqArrayArray(10), Array(String)),

    -- Replay
    has_replay_events SimpleAggregateFunction(max, Boolean)
,

    -- Indexes
    INDEX event_names_bloom_filter event_names TYPE bloom_filter() GRANULARITY 1,
    INDEX flag_keys_bloom_filter flag_keys TYPE bloom_filter() GRANULARITY 1,
    INDEX hosts_bloom_filter hosts TYPE bloom_filter() GRANULARITY 1,
    INDEX emails_bloom_filter emails TYPE bloom_filter() GRANULARITY 1
) ENGINE = ReplicatedAggregatingMergeTree('/clickhouse/tables/{shard}/posthog.raw_sessions_v3', '{replica}')

PARTITION BY toYYYYMM(session_timestamp)
ORDER BY (
    team_id,
    session_timestamp,
    session_id_v7
)
SETTINGS parts_to_delay_insert = 250, max_delay_to_insert = 10, parts_to_throw_insert = 1000

CREATE TABLE IF NOT EXISTS writable_raw_sessions_v3
(
    team_id Int64,

    -- Both UInt128 and UUID are imperfect choices here
    -- see https://michcioperz.com/wiki/clickhouse-uuid-ordering/
    -- but also see https://github.com/ClickHouse/ClickHouse/issues/77226 and hope
    -- right now choose UInt128 as that's the type of events.$session_id_uuid, but in the future we will probably want to switch everything to the new CH UUID type (when it's released)
    session_id_v7 UInt128,
    -- Ideally we would not need to store this separately, as the ID *is* the timestamp
    -- Unfortunately for now, chaining clickhouse functions to extract the timestamp will break indexes / partition pruning, so do this workaround
    -- again, when the new CH UUID type is released, we should try to switch to that and remove the separate timestamp column
    session_timestamp DateTime64 DEFAULT fromUnixTimestamp64Milli(toUInt64(bitShiftRight(session_id_v7, 80))),

    -- ClickHouse will pick the latest value of distinct_id for the session
    -- this is fine since even if the distinct_id changes during a session
    -- it will still (or should still) map to the same person
    distinct_id AggregateFunction(argMax, String, DateTime64(6, 'UTC')),
    distinct_ids AggregateFunction(groupUniqArray, String),

    min_timestamp SimpleAggregateFunction(min, DateTime64(6, 'UTC')),
    max_timestamp SimpleAggregateFunction(max, DateTime64(6, 'UTC')),
    max_inserted_at SimpleAggregateFunction(max, DateTime64(6, 'UTC')),

    -- urls
    urls SimpleAggregateFunction(groupUniqArrayArray(2000), Array(String)),
    entry_url AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    end_url AggregateFunction(argMax, Nullable(String), DateTime64(6, 'UTC')),
    last_external_click_url AggregateFunction(argMax, Nullable(String), DateTime64(6, 'UTC')),

    -- device
    browser AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    browser_version AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    os AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    os_version AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    device_type AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    viewport_width AggregateFunction(argMin, Nullable(Int64), DateTime64(6, 'UTC')),
    viewport_height AggregateFunction(argMin, Nullable(Int64), DateTime64(6, 'UTC')),

    -- geoip
    -- only store the properties we actually use, as there's tons, see https://posthog.com/docs/cdp/geoip-enrichment
    geoip_country_code AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    geoip_subdivision_1_code AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    geoip_subdivision_1_name AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    geoip_subdivision_city_name AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    geoip_time_zone AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),

    -- attribution
    entry_referring_domain AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    entry_utm_source AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    entry_utm_campaign AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    entry_utm_medium AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    entry_utm_term AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    entry_utm_content AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    entry_gclid AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    entry_gad_source AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    entry_fbclid AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),

    -- for channel type calculation, it's enough to know if these were present
    entry_has_gclid AggregateFunction(argMin, Boolean, DateTime64(6, 'UTC')),
    entry_has_fbclid AggregateFunction(argMin, Boolean, DateTime64(6, 'UTC')),

    -- for lower-tier ad ids, just put them in a map, and set of the ones present
    entry_ad_ids_map AggregateFunction(argMin, Map(String, String), DateTime64(6, 'UTC')),
    entry_ad_ids_set AggregateFunction(argMin, Array(String), DateTime64(6, 'UTC')),

    -- channel type properties tuple - to reduce redundant reading of the timestamp when loading all of these columns
    -- utm_source, utm_medium, utm_campaign, referring domain, has_gclid, has_fbclid, gad_source
    entry_channel_type_properties AggregateFunction(argMin, Tuple(Nullable(String), Nullable(String), Nullable(String), Nullable(String), Boolean, Boolean, Nullable(String)), DateTime64(6, 'UTC')),

    -- Count pageview, autocapture, and screen events for providing totals.
    -- Use uniqExact instead of count, so that inserting events can be idempotent. This is necessary as sometimes we see
    -- events being inserted multiple times to be deduped later, but that can trigger multiple rows here.
    -- Additionally, idempotency is useful for backfilling, as we can just reinsert the same events without worrying.
    pageview_uniq AggregateFunction(uniqExact, Nullable(UUID)),
    autocapture_uniq AggregateFunction(uniqExact, Nullable(UUID)),
    screen_uniq AggregateFunction(uniqExact, Nullable(UUID)),

    -- As a performance optimisation, also keep track of the uniq events for all of these combined.
    -- This is a much more efficient way of calculating the bounce rate, as >2 means not a bounce
    page_screen_uniq_up_to AggregateFunction(uniqUpTo(1), Nullable(UUID)),
    has_autocapture SimpleAggregateFunction(max, Boolean),

    -- Flags - store every seen value for each flag
    flag_values AggregateFunction(groupUniqArrayMap, Map(String, String)),
    flag_keys SimpleAggregateFunction(groupUniqArrayArray, Array(String)),

    -- Event names - store unique event names seen in this session
    event_names SimpleAggregateFunction(groupUniqArrayArray(2000), Array(String)),

    -- Hosts - store unique hostnames seen in this session (extracted from $host property)
    hosts SimpleAggregateFunction(groupUniqArrayArray(100), Array(String)),

    -- Emails - store unique emails seen in this session (extracted from person_properties.email)
    emails SimpleAggregateFunction(groupUniqArrayArray(10), Array(String)),

    -- Replay
    has_replay_events SimpleAggregateFunction(max, Boolean)
) ENGINE = Distributed('posthog', 'default', 'sharded_raw_sessions_v3', cityHash64(session_id_v7))

CREATE TABLE IF NOT EXISTS raw_sessions_v3
(
    team_id Int64,

    -- Both UInt128 and UUID are imperfect choices here
    -- see https://michcioperz.com/wiki/clickhouse-uuid-ordering/
    -- but also see https://github.com/ClickHouse/ClickHouse/issues/77226 and hope
    -- right now choose UInt128 as that's the type of events.$session_id_uuid, but in the future we will probably want to switch everything to the new CH UUID type (when it's released)
    session_id_v7 UInt128,
    -- Ideally we would not need to store this separately, as the ID *is* the timestamp
    -- Unfortunately for now, chaining clickhouse functions to extract the timestamp will break indexes / partition pruning, so do this workaround
    -- again, when the new CH UUID type is released, we should try to switch to that and remove the separate timestamp column
    session_timestamp DateTime64 MATERIALIZED fromUnixTimestamp64Milli(toUInt64(bitShiftRight(session_id_v7, 80))),

    -- ClickHouse will pick the latest value of distinct_id for the session
    -- this is fine since even if the distinct_id changes during a session
    -- it will still (or should still) map to the same person
    distinct_id AggregateFunction(argMax, String, DateTime64(6, 'UTC')),
    distinct_ids AggregateFunction(groupUniqArray, String),

    min_timestamp SimpleAggregateFunction(min, DateTime64(6, 'UTC')),
    max_timestamp SimpleAggregateFunction(max, DateTime64(6, 'UTC')),
    max_inserted_at SimpleAggregateFunction(max, DateTime64(6, 'UTC')),

    -- urls
    urls SimpleAggregateFunction(groupUniqArrayArray(2000), Array(String)),
    entry_url AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    end_url AggregateFunction(argMax, Nullable(String), DateTime64(6, 'UTC')),
    last_external_click_url AggregateFunction(argMax, Nullable(String), DateTime64(6, 'UTC')),

    -- device
    browser AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    browser_version AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    os AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    os_version AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    device_type AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    viewport_width AggregateFunction(argMin, Nullable(Int64), DateTime64(6, 'UTC')),
    viewport_height AggregateFunction(argMin, Nullable(Int64), DateTime64(6, 'UTC')),

    -- geoip
    -- only store the properties we actually use, as there's tons, see https://posthog.com/docs/cdp/geoip-enrichment
    geoip_country_code AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    geoip_subdivision_1_code AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    geoip_subdivision_1_name AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    geoip_subdivision_city_name AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    geoip_time_zone AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),

    -- attribution
    entry_referring_domain AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    entry_utm_source AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    entry_utm_campaign AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    entry_utm_medium AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    entry_utm_term AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    entry_utm_content AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    entry_gclid AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    entry_gad_source AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),
    entry_fbclid AggregateFunction(argMin, Nullable(String), DateTime64(6, 'UTC')),

    -- for channel type calculation, it's enough to know if these were present
    entry_has_gclid AggregateFunction(argMin, Boolean, DateTime64(6, 'UTC')),
    entry_has_fbclid AggregateFunction(argMin, Boolean, DateTime64(6, 'UTC')),

    -- for lower-tier ad ids, just put them in a map, and set of the ones present
    entry_ad_ids_map AggregateFunction(argMin, Map(String, String), DateTime64(6, 'UTC')),
    entry_ad_ids_set AggregateFunction(argMin, Array(String), DateTime64(6, 'UTC')),

    -- channel type properties tuple - to reduce redundant reading of the timestamp when loading all of these columns
    -- utm_source, utm_medium, utm_campaign, referring domain, has_gclid, has_fbclid, gad_source
    entry_channel_type_properties AggregateFunction(argMin, Tuple(Nullable(String), Nullable(String), Nullable(String), Nullable(String), Boolean, Boolean, Nullable(String)), DateTime64(6, 'UTC')),

    -- Count pageview, autocapture, and screen events for providing totals.
    -- Use uniqExact instead of count, so that inserting events can be idempotent. This is necessary as sometimes we see
    -- events being inserted multiple times to be deduped later, but that can trigger multiple rows here.
    -- Additionally, idempotency is useful for backfilling, as we can just reinsert the same events without worrying.
    pageview_uniq AggregateFunction(uniqExact, Nullable(UUID)),
    autocapture_uniq AggregateFunction(uniqExact, Nullable(UUID)),
    screen_uniq AggregateFunction(uniqExact, Nullable(UUID)),

    -- As a performance optimisation, also keep track of the uniq events for all of these combined.
    -- This is a much more efficient way of calculating the bounce rate, as >2 means not a bounce
    page_screen_uniq_up_to AggregateFunction(uniqUpTo(1), Nullable(UUID)),
    has_autocapture SimpleAggregateFunction(max, Boolean),

    -- Flags - store every seen value for each flag
    flag_values AggregateFunction(groupUniqArrayMap, Map(String, String)),
    flag_keys SimpleAggregateFunction(groupUniqArrayArray, Array(String)),

    -- Event names - store unique event names seen in this session
    event_names SimpleAggregateFunction(groupUniqArrayArray(2000), Array(String)),

    -- Hosts - store unique hostnames seen in this session (extracted from $host property)
    hosts SimpleAggregateFunction(groupUniqArrayArray(100), Array(String)),

    -- Emails - store unique emails seen in this session (extracted from person_properties.email)
    emails SimpleAggregateFunction(groupUniqArrayArray(10), Array(String)),

    -- Replay
    has_replay_events SimpleAggregateFunction(max, Boolean)
) ENGINE = Distributed('posthog', 'default', 'sharded_raw_sessions_v3', cityHash64(session_id_v7))

CREATE OR REPLACE VIEW raw_sessions_v3_v AS
SELECT
    session_id_v7,
    session_timestamp,
    team_id,

    argMaxMerge(distinct_id) as distinct_id,
    groupUniqArrayMerge(distinct_ids) AS distinct_ids,

    min(min_timestamp) as min_timestamp,
    max(max_timestamp) as max_timestamp,
    max(max_inserted_at) as max_inserted_at,

    -- urls
    groupUniqArrayArray(2000)(urls) AS urls,
    argMinMerge(entry_url) as entry_url,
    argMaxMerge(end_url) as end_url,
    argMaxMerge(last_external_click_url) as last_external_click_url,

    -- device
    argMinMerge(browser) as browser,
    argMinMerge(browser_version) as browser_version,
    argMinMerge(os) as os,
    argMinMerge(os_version) as os_version,
    argMinMerge(device_type) as device_type,
    argMinMerge(viewport_width) as viewport_width,
    argMinMerge(viewport_height) as viewport_height,

    -- geoip
    argMinMerge(geoip_country_code) as geoip_country_code,
    argMinMerge(geoip_subdivision_1_code) as geoip_subdivision_1_code,
    argMinMerge(geoip_subdivision_1_name) as geoip_subdivision_1_name,
    argMinMerge(geoip_subdivision_city_name) as geoip_subdivision_city_name,
    argMinMerge(geoip_time_zone) as geoip_time_zone,

    -- attribution
    argMinMerge(entry_utm_source) as entry_utm_source,
    argMinMerge(entry_utm_campaign) as entry_utm_campaign,
    argMinMerge(entry_utm_medium) as entry_utm_medium,
    argMinMerge(entry_utm_term) as entry_utm_term,
    argMinMerge(entry_utm_content) as entry_utm_content,
    argMinMerge(entry_referring_domain) as entry_referring_domain,
    argMinMerge(entry_gclid) as entry_gclid,
    argMinMerge(entry_gad_source) as entry_gad_source,
    argMinMerge(entry_fbclid) as entry_fbclid,

    argMinMerge(entry_has_gclid) as entry_has_gclid,
    argMinMerge(entry_has_fbclid) as entry_has_fbclid,

    argMinMerge(entry_ad_ids_map) as entry_ad_ids_map,
    argMinMerge(entry_ad_ids_set) as entry_ad_ids_set,

    argMinMerge(entry_channel_type_properties) as entry_channel_type_properties,

    -- counts
    uniqExactMerge(pageview_uniq) as pageview_uniq,
    uniqExactMerge(autocapture_uniq) as autocapture_uniq,
    uniqExactMerge(screen_uniq) as screen_uniq,

    -- perf
    uniqUpToMerge(1)(page_screen_uniq_up_to) as page_screen_uniq_up_to,
    max(has_autocapture) as has_autocapture,

    -- flags
    groupUniqArrayMapMerge(flag_values) as flag_values,
    groupUniqArrayArray(flag_keys) as flag_keys,

    -- event names
    groupUniqArrayArray(2000)(event_names) as event_names,

    -- hosts
    groupUniqArrayArray(100)(hosts) as hosts,

    -- emails
    groupUniqArrayArray(10)(emails) as emails,

    -- replay
    max(has_replay_events) as has_replay_events
FROM default.raw_sessions_v3
GROUP BY session_id_v7, session_timestamp, team_id
