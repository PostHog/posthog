# Distributed tables, views and dictionaries that queries read from.




module "web_pre_aggregated_teams_dict" {
  source = "../../lib/dictionary"

  enabled     = local.read && !contains(local.deployment.exclude, "web_pre_aggregated_teams_dict")
  database    = var.database
  name        = "web_pre_aggregated_teams_dict"
  primary_key = ["team_id"]
  attributes = [
    { name = "team_id", type = "UInt64" },
  ]
  source_clause = "CLICKHOUSE(USER '${var.dictionary_user}'${local.dictionary_password_clause} QUERY 'SELECT     team_id FROM     `${var.database}`.`web_pre_aggregated_teams` FINAL WHERE version > 0')"
  layout        = "HASHED()"
  lifetime      = "MIN 3000 MAX 3600"
  override      = try(local.deployment.overrides["web_pre_aggregated_teams_dict"], {})

  depends_on = [
    module.web_pre_aggregated_teams_family,
  ]
}
