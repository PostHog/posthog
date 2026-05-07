CREATE TABLE IF NOT EXISTS `web_pre_aggregated_teams`  (
    team_id UInt64,
    enabled_by String DEFAULT 'system',
    version UInt32 DEFAULT toUnixTimestamp(now())
) ENGINE = ReplicatedReplacingMergeTree('/clickhouse/tables/noshard/posthog.web_analytics_team_selection', '{replica}-{shard}', version)
ORDER BY (team_id);

INSERT INTO `web_pre_aggregated_teams` (team_id, enabled_by) VALUES
  (1, 'system'),
(2, 'system'),
(55348, 'system'),
(47074, 'system'),
(12669, 'system'),
(1589, 'system'),
(117126, 'system');

CREATE DICTIONARY IF NOT EXISTS `web_pre_aggregated_teams_dict`  (
    team_id UInt64
)
PRIMARY KEY team_id
SOURCE(CLICKHOUSE(QUERY 'SELECT     team_id FROM     `default`.`web_pre_aggregated_teams` FINAL WHERE version > 0' USER 'default' PASSWORD ''))
LIFETIME(MIN 3000 MAX 3600)
LAYOUT(HASHED())
