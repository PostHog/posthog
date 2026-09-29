WITH dictGet('person_group_membership_config_dict', ('group_type_index', 'enabled'), tuple(toInt64(team_id))) AS config
SELECT
    team_id,
    config.1 AS group_type_index,
    JSONExtractString(properties, concat('$group_', toString(group_type_index))) AS group_key,
    distinct_id,
    min(timestamp) AS first_seen,
    max(timestamp) AS last_seen
FROM posthog.kafka_person_group_membership
WHERE config.2 = 1
    AND group_type_index <= 4
    AND person_mode != 'propertyless'
    AND group_key != ''
GROUP BY team_id, group_type_index, group_key, distinct_id
