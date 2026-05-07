DROP DICTIONARY IF EXISTS `web_pre_aggregated_teams_dict`

CREATE DICTIONARY IF NOT EXISTS `web_pre_aggregated_teams_dict`  (
    team_id UInt64
)
PRIMARY KEY team_id
SOURCE(CLICKHOUSE(QUERY 'SELECT     team_id FROM     `default`.`web_pre_aggregated_teams` FINAL WHERE version > 0' USER 'default' PASSWORD ''))
LIFETIME(MIN 3000 MAX 3600)
LAYOUT(HASHED())
