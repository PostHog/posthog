-- Country dimension derived from events and enriched with an uploaded country->region lookup.
-- One row per ISO-2 country_code (the natural key). Every column aliased (required by view-create).
-- Replace <country_region_lookup> with the uploaded lookup table (columns: country_code, region, continent).
SELECT
    seen.country_code                              AS country_code,
    any(lk.region)                                 AS region,
    any(lk.continent)                              AS continent,
    count()                                        AS events_seen   -- optional: popularity, for QA
FROM (
    SELECT
        upper(properties.$geoip_country_code)      AS country_code
    FROM events
    WHERE properties.$geoip_country_code != ''
      AND timestamp >= now() - INTERVAL 90 DAY
) AS seen
LEFT JOIN <country_region_lookup> AS lk ON seen.country_code = lk.country_code
GROUP BY country_code
-- Materialize on a slow schedule (7day/30day): country attributes barely change but are read constantly.
