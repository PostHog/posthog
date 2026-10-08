# Production objects from before this catalogue, declared from their live definitions. Only Cloud roots
# in posthog-cloud-infra list them.

variable "node" {
  type    = any
  default = null
}

variable "database" {
  type    = string
  default = "posthog"
}

variable "objects" {
  description = "Names of the objects to create."
  type        = set(string)
}

variable "test" {
  description = "Use the definitions the test suite expects."
  type        = bool
  default     = false
}

variable "deployment" { type = any }

locals {
  deployment = merge({ overrides = {} }, var.deployment)
}

module "buffer_events_json" {
  source = "../../lib/table"
  node   = var.node

  enabled  = contains(var.objects, "buffer_events_json")
  database = var.database
  name     = "buffer_events_json"
  override = try(local.deployment.overrides["buffer_events_json"], {})
  engine   = "Buffer('${var.database}', 'sharded_events_json', 12, 5, 45, 100000, 200000, 536870912, 2147483648)"
  columns = [
    { name = "uuid", type = "UUID" },
    { name = "event", type = "String" },
    { name = "group0_properties", type = "String" },
    { name = "group1_properties", type = "String" },
    { name = "group2_properties", type = "String" },
    { name = "group3_properties", type = "String" },
    { name = "group4_properties", type = "String" },
    { name = "person_created_at", type = "DateTime64(3)", codec = "GCD, Default" },
    { name = "group0_created_at", type = "DateTime64(3)", codec = "GCD, Default" },
    { name = "group1_created_at", type = "DateTime64(3)", codec = "GCD, Default" },
    { name = "group2_created_at", type = "DateTime64(3)", codec = "GCD, Default" },
    { name = "group3_created_at", type = "DateTime64(3)", codec = "GCD, Default" },
    { name = "group4_created_at", type = "DateTime64(3)", codec = "GCD, Default" },
    { name = "inserted_at", type = "DateTime64(6, 'UTC')", default_expression = "now64()", codec = "GCD, Default" },
    { name = "person_mode", type = "Enum8('full' = 0, 'propertyless' = 1, 'force_upgrade' = 2)" },
    { name = "consumer_breadcrumbs", type = "Array(String)" },
    { name = "historical_migration", type = "Bool" },
    { name = "total_event_size", type = "UInt32", codec = "T64, Default" },
    { name = "timestamp", type = "DateTime64(6, 'UTC')", codec = "GCD, Default" },
    { name = "team_id", type = "Int64" },
    { name = "distinct_id", type = "String" },
    { name = "elements_hash", type = "String" },
    { name = "created_at", type = "DateTime64(6, 'UTC')", default_expression = "now()", codec = "GCD, Default" },
    { name = "captured_at", type = "DateTime64(6, 'UTC')", default_expression = "now()", codec = "GCD, Default" },
    { name = "_timestamp", type = "DateTime", codec = "T64, Default" },
    { name = "_offset", type = "UInt64", codec = "T64, Default" },
    { name = "_partition", type = "UInt64", codec = "T64, Default" },
    { name = "elements_chain", type = "String" },
    { name = "elements_chain_href", type = "String", default_expression = "extract(elements_chain, '(?::|\")href=\"(.*?)\"')" },
    { name = "elements_chain_texts", type = "Array(String)", default_expression = "arrayDistinct(extractAll(elements_chain, '(?::|\")text=\"(.*?)\"'))" },
    { name = "elements_chain_elements", type = "Array(Enum8('a' = 1, 'button' = 2, 'form' = 3, 'input' = 4, 'select' = 5, 'textarea' = 6, 'label' = 7))", default_expression = "arrayDistinct(extractAll(elements_chain, '(?:^|;)(a|button|form|input|select|textarea|label)(?:\\.|$|:)'))" },
    { name = "elements_chain_ids", type = "Array(String)", default_expression = "arrayDistinct(extractAll(elements_chain, '(?::|\")attr_id=\"(.*?)\"'))" },
    { name = "person_id", type = "UUID" },
    { name = "properties", type = "JSON(max_dynamic_paths=512, `$browser` LowCardinality(String), `$browser_language` LowCardinality(String), `$browser_version` LowCardinality(String), `$config_defaults` LowCardinality(String), `$device_type` LowCardinality(String), `$exception_functions` Array(String), `$exception_list` Array(JSON(max_dynamic_paths=20, type String, value String)), `$exception_sources` Array(String), `$exception_types` Array(String), `$exception_values` Array(String), `$feature_flags` Map(LowCardinality(String), LowCardinality(String)), `$geoip_city_name` LowCardinality(String), `$geoip_continent_code` LowCardinality(String), `$geoip_continent_name` LowCardinality(String), `$geoip_country_code` LowCardinality(String), `$geoip_country_name` LowCardinality(String), `$geoip_subdivision_1_name` LowCardinality(String), `$geoip_time_zone` LowCardinality(String), `$group_0` String, `$group_1` String, `$group_2` String, `$group_3` String, `$group_4` String, `$lib` LowCardinality(String), `$lib_version` LowCardinality(String), `$mcp_listed_tool_names` Array(String), `$os` LowCardinality(String), `$os_version` LowCardinality(String), `$session_id` String, `$timezone` LowCardinality(String), `$window_id` String)" },
    { name = "temporary_properties", type = "JSON(max_dynamic_paths=64)" },
    { name = "person_properties", type = "JSON(max_dynamic_paths=128, `$browser` LowCardinality(String), `$browser_language` LowCardinality(String), `$browser_version` LowCardinality(String), `$device_type` LowCardinality(String), `$geoip_city_name` LowCardinality(String), `$geoip_continent_code` LowCardinality(String), `$geoip_continent_name` LowCardinality(String), `$geoip_country_code` LowCardinality(String), `$geoip_country_name` LowCardinality(String), `$geoip_subdivision_1_name` LowCardinality(String), `$geoip_time_zone` LowCardinality(String), `$initial_browser` LowCardinality(String), `$initial_browser_language` LowCardinality(String), `$initial_browser_version` LowCardinality(String), `$initial_device_type` LowCardinality(String), `$initial_geoip_city_name` LowCardinality(String), `$initial_geoip_continent_code` LowCardinality(String), `$initial_geoip_continent_name` LowCardinality(String), `$initial_geoip_country_code` LowCardinality(String), `$initial_geoip_country_name` LowCardinality(String), `$initial_geoip_subdivision_1_name` LowCardinality(String), `$initial_geoip_time_zone` LowCardinality(String), `$initial_os` LowCardinality(String), `$initial_os_version` LowCardinality(String), `$os` LowCardinality(String), `$os_version` LowCardinality(String))" },
    { name = "properties_null_keys", type = "Array(LowCardinality(String))" },
    { name = "temporary_properties_null_keys", type = "Array(LowCardinality(String))" },
    { name = "person_properties_null_keys", type = "Array(LowCardinality(String))" },
  ]
}

module "buffer_events_json_historical" {
  source = "../../lib/table"
  node   = var.node

  enabled  = contains(var.objects, "buffer_events_json_historical")
  database = var.database
  name     = "buffer_events_json_historical"
  override = try(local.deployment.overrides["buffer_events_json_historical"], {})
  engine   = "Buffer('${var.database}', 'sharded_events_json', 2, 300, 900, 150000, 300000, 1073741824, 3221225472, 600, 75000, 805306368)"
  columns = [
    { name = "uuid", type = "UUID" },
    { name = "event", type = "String" },
    { name = "group0_properties", type = "String" },
    { name = "group1_properties", type = "String" },
    { name = "group2_properties", type = "String" },
    { name = "group3_properties", type = "String" },
    { name = "group4_properties", type = "String" },
    { name = "person_created_at", type = "DateTime64(3)", codec = "GCD, Default" },
    { name = "group0_created_at", type = "DateTime64(3)", codec = "GCD, Default" },
    { name = "group1_created_at", type = "DateTime64(3)", codec = "GCD, Default" },
    { name = "group2_created_at", type = "DateTime64(3)", codec = "GCD, Default" },
    { name = "group3_created_at", type = "DateTime64(3)", codec = "GCD, Default" },
    { name = "group4_created_at", type = "DateTime64(3)", codec = "GCD, Default" },
    { name = "inserted_at", type = "DateTime64(6, 'UTC')", default_expression = "now64()", codec = "GCD, Default" },
    { name = "person_mode", type = "Enum8('full' = 0, 'propertyless' = 1, 'force_upgrade' = 2)" },
    { name = "consumer_breadcrumbs", type = "Array(String)" },
    { name = "historical_migration", type = "Bool" },
    { name = "total_event_size", type = "UInt32", codec = "T64, Default" },
    { name = "timestamp", type = "DateTime64(6, 'UTC')", codec = "GCD, Default" },
    { name = "team_id", type = "Int64" },
    { name = "distinct_id", type = "String" },
    { name = "elements_hash", type = "String" },
    { name = "created_at", type = "DateTime64(6, 'UTC')", default_expression = "now()", codec = "GCD, Default" },
    { name = "captured_at", type = "DateTime64(6, 'UTC')", default_expression = "now()", codec = "GCD, Default" },
    { name = "_timestamp", type = "DateTime", codec = "T64, Default" },
    { name = "_offset", type = "UInt64", codec = "T64, Default" },
    { name = "_partition", type = "UInt64", codec = "T64, Default" },
    { name = "elements_chain", type = "String" },
    { name = "elements_chain_href", type = "String", default_expression = "extract(elements_chain, '(?::|\")href=\"(.*?)\"')" },
    { name = "elements_chain_texts", type = "Array(String)", default_expression = "arrayDistinct(extractAll(elements_chain, '(?::|\")text=\"(.*?)\"'))" },
    { name = "elements_chain_elements", type = "Array(Enum8('a' = 1, 'button' = 2, 'form' = 3, 'input' = 4, 'select' = 5, 'textarea' = 6, 'label' = 7))", default_expression = "arrayDistinct(extractAll(elements_chain, '(?:^|;)(a|button|form|input|select|textarea|label)(?:\\.|$|:)'))" },
    { name = "elements_chain_ids", type = "Array(String)", default_expression = "arrayDistinct(extractAll(elements_chain, '(?::|\")attr_id=\"(.*?)\"'))" },
    { name = "person_id", type = "UUID" },
    { name = "properties", type = "JSON(max_dynamic_paths=512, `$browser` LowCardinality(String), `$browser_language` LowCardinality(String), `$browser_version` LowCardinality(String), `$config_defaults` LowCardinality(String), `$device_type` LowCardinality(String), `$exception_functions` Array(String), `$exception_list` Array(JSON(max_dynamic_paths=20, type String, value String)), `$exception_sources` Array(String), `$exception_types` Array(String), `$exception_values` Array(String), `$feature_flags` Map(LowCardinality(String), LowCardinality(String)), `$geoip_city_name` LowCardinality(String), `$geoip_continent_code` LowCardinality(String), `$geoip_continent_name` LowCardinality(String), `$geoip_country_code` LowCardinality(String), `$geoip_country_name` LowCardinality(String), `$geoip_subdivision_1_name` LowCardinality(String), `$geoip_time_zone` LowCardinality(String), `$group_0` String, `$group_1` String, `$group_2` String, `$group_3` String, `$group_4` String, `$lib` LowCardinality(String), `$lib_version` LowCardinality(String), `$mcp_listed_tool_names` Array(String), `$os` LowCardinality(String), `$os_version` LowCardinality(String), `$session_id` String, `$timezone` LowCardinality(String), `$window_id` String)" },
    { name = "temporary_properties", type = "JSON(max_dynamic_paths=64)" },
    { name = "person_properties", type = "JSON(max_dynamic_paths=128, `$browser` LowCardinality(String), `$browser_language` LowCardinality(String), `$browser_version` LowCardinality(String), `$device_type` LowCardinality(String), `$geoip_city_name` LowCardinality(String), `$geoip_continent_code` LowCardinality(String), `$geoip_continent_name` LowCardinality(String), `$geoip_country_code` LowCardinality(String), `$geoip_country_name` LowCardinality(String), `$geoip_subdivision_1_name` LowCardinality(String), `$geoip_time_zone` LowCardinality(String), `$initial_browser` LowCardinality(String), `$initial_browser_language` LowCardinality(String), `$initial_browser_version` LowCardinality(String), `$initial_device_type` LowCardinality(String), `$initial_geoip_city_name` LowCardinality(String), `$initial_geoip_continent_code` LowCardinality(String), `$initial_geoip_continent_name` LowCardinality(String), `$initial_geoip_country_code` LowCardinality(String), `$initial_geoip_country_name` LowCardinality(String), `$initial_geoip_subdivision_1_name` LowCardinality(String), `$initial_geoip_time_zone` LowCardinality(String), `$initial_os` LowCardinality(String), `$initial_os_version` LowCardinality(String), `$os` LowCardinality(String), `$os_version` LowCardinality(String))" },
    { name = "properties_null_keys", type = "Array(LowCardinality(String))" },
    { name = "temporary_properties_null_keys", type = "Array(LowCardinality(String))" },
    { name = "person_properties_null_keys", type = "Array(LowCardinality(String))" },
  ]
}

module "new_buffer_events_json" {
  source = "../../lib/table"
  node   = var.node

  enabled  = contains(var.objects, "new_buffer_events_json")
  database = var.database
  name     = "new_buffer_events_json"
  override = try(local.deployment.overrides["new_buffer_events_json"], {})
  engine   = "Buffer('${var.database}', 'sharded_events_json', 24, 120, 180, 150000, 200000, 1610612736, 2147483648, 90, 100000, 1073741824)"
  columns = [
    { name = "uuid", type = "UUID" },
    { name = "event", type = "String" },
    { name = "group0_properties", type = "String" },
    { name = "group1_properties", type = "String" },
    { name = "group2_properties", type = "String" },
    { name = "group3_properties", type = "String" },
    { name = "group4_properties", type = "String" },
    { name = "person_created_at", type = "DateTime64(3)", codec = "GCD, Default" },
    { name = "group0_created_at", type = "DateTime64(3)", codec = "GCD, Default" },
    { name = "group1_created_at", type = "DateTime64(3)", codec = "GCD, Default" },
    { name = "group2_created_at", type = "DateTime64(3)", codec = "GCD, Default" },
    { name = "group3_created_at", type = "DateTime64(3)", codec = "GCD, Default" },
    { name = "group4_created_at", type = "DateTime64(3)", codec = "GCD, Default" },
    { name = "inserted_at", type = "DateTime64(6, 'UTC')", default_expression = "now64()", codec = "GCD, Default" },
    { name = "person_mode", type = "Enum8('full' = 0, 'propertyless' = 1, 'force_upgrade' = 2)" },
    { name = "consumer_breadcrumbs", type = "Array(String)" },
    { name = "historical_migration", type = "Bool" },
    { name = "total_event_size", type = "UInt32", codec = "T64, Default" },
    { name = "timestamp", type = "DateTime64(6, 'UTC')", codec = "GCD, Default" },
    { name = "team_id", type = "Int64" },
    { name = "distinct_id", type = "String" },
    { name = "elements_hash", type = "String" },
    { name = "created_at", type = "DateTime64(6, 'UTC')", default_expression = "now()", codec = "GCD, Default" },
    { name = "captured_at", type = "DateTime64(6, 'UTC')", default_expression = "now()", codec = "GCD, Default" },
    { name = "_timestamp", type = "DateTime", codec = "T64, Default" },
    { name = "_offset", type = "UInt64", codec = "T64, Default" },
    { name = "_partition", type = "UInt64", codec = "T64, Default" },
    { name = "elements_chain", type = "String" },
    { name = "elements_chain_href", type = "String", default_expression = "extract(elements_chain, '(?::|\")href=\"(.*?)\"')" },
    { name = "elements_chain_texts", type = "Array(String)", default_expression = "arrayDistinct(extractAll(elements_chain, '(?::|\")text=\"(.*?)\"'))" },
    { name = "elements_chain_elements", type = "Array(Enum8('a' = 1, 'button' = 2, 'form' = 3, 'input' = 4, 'select' = 5, 'textarea' = 6, 'label' = 7))", default_expression = "arrayDistinct(extractAll(elements_chain, '(?:^|;)(a|button|form|input|select|textarea|label)(?:\\.|$|:)'))" },
    { name = "elements_chain_ids", type = "Array(String)", default_expression = "arrayDistinct(extractAll(elements_chain, '(?::|\")attr_id=\"(.*?)\"'))" },
    { name = "person_id", type = "UUID" },
    { name = "properties", type = "JSON(max_dynamic_paths=512, `$browser` LowCardinality(String), `$browser_language` LowCardinality(String), `$browser_version` LowCardinality(String), `$config_defaults` LowCardinality(String), `$device_type` LowCardinality(String), `$exception_functions` Array(String), `$exception_list` Array(JSON(max_dynamic_paths=20, type String, value String)), `$exception_sources` Array(String), `$exception_types` Array(String), `$exception_values` Array(String), `$feature_flags` Map(LowCardinality(String), LowCardinality(String)), `$geoip_city_name` LowCardinality(String), `$geoip_continent_code` LowCardinality(String), `$geoip_continent_name` LowCardinality(String), `$geoip_country_code` LowCardinality(String), `$geoip_country_name` LowCardinality(String), `$geoip_subdivision_1_name` LowCardinality(String), `$geoip_time_zone` LowCardinality(String), `$group_0` String, `$group_1` String, `$group_2` String, `$group_3` String, `$group_4` String, `$lib` LowCardinality(String), `$lib_version` LowCardinality(String), `$mcp_listed_tool_names` Array(String), `$os` LowCardinality(String), `$os_version` LowCardinality(String), `$session_id` String, `$timezone` LowCardinality(String), `$window_id` String)" },
    { name = "temporary_properties", type = "JSON(max_dynamic_paths=64)" },
    { name = "person_properties", type = "JSON(max_dynamic_paths=128, `$browser` LowCardinality(String), `$browser_language` LowCardinality(String), `$browser_version` LowCardinality(String), `$device_type` LowCardinality(String), `$geoip_city_name` LowCardinality(String), `$geoip_continent_code` LowCardinality(String), `$geoip_continent_name` LowCardinality(String), `$geoip_country_code` LowCardinality(String), `$geoip_country_name` LowCardinality(String), `$geoip_subdivision_1_name` LowCardinality(String), `$geoip_time_zone` LowCardinality(String), `$initial_browser` LowCardinality(String), `$initial_browser_language` LowCardinality(String), `$initial_browser_version` LowCardinality(String), `$initial_device_type` LowCardinality(String), `$initial_geoip_city_name` LowCardinality(String), `$initial_geoip_continent_code` LowCardinality(String), `$initial_geoip_continent_name` LowCardinality(String), `$initial_geoip_country_code` LowCardinality(String), `$initial_geoip_country_name` LowCardinality(String), `$initial_geoip_subdivision_1_name` LowCardinality(String), `$initial_geoip_time_zone` LowCardinality(String), `$initial_os` LowCardinality(String), `$initial_os_version` LowCardinality(String), `$os` LowCardinality(String), `$os_version` LowCardinality(String))" },
    { name = "properties_null_keys", type = "Array(LowCardinality(String))" },
    { name = "temporary_properties_null_keys", type = "Array(LowCardinality(String))" },
    { name = "person_properties_null_keys", type = "Array(LowCardinality(String))" },
  ]
}

module "ingest_events_json" {
  source = "../../lib/table"
  node   = var.node

  enabled  = contains(var.objects, "ingest_events_json")
  database = var.database
  name     = "ingest_events_json"
  override = try(local.deployment.overrides["ingest_events_json"], {})
  engine   = "`Null`"
  columns = [
    { name = "uuid", type = "UUID" },
    { name = "event", type = "String" },
    { name = "group0_properties", type = "String" },
    { name = "group1_properties", type = "String" },
    { name = "group2_properties", type = "String" },
    { name = "group3_properties", type = "String" },
    { name = "group4_properties", type = "String" },
    { name = "person_created_at", type = "DateTime64(3)", codec = "GCD, Default" },
    { name = "group0_created_at", type = "DateTime64(3)", codec = "GCD, Default" },
    { name = "group1_created_at", type = "DateTime64(3)", codec = "GCD, Default" },
    { name = "group2_created_at", type = "DateTime64(3)", codec = "GCD, Default" },
    { name = "group3_created_at", type = "DateTime64(3)", codec = "GCD, Default" },
    { name = "group4_created_at", type = "DateTime64(3)", codec = "GCD, Default" },
    { name = "inserted_at", type = "DateTime64(6, 'UTC')", default_expression = "now64()", codec = "GCD, Default" },
    { name = "person_mode", type = "Enum8('full' = 0, 'propertyless' = 1, 'force_upgrade' = 2)" },
    { name = "consumer_breadcrumbs", type = "Array(String)" },
    { name = "historical_migration", type = "Bool" },
    { name = "total_event_size", type = "UInt32", codec = "T64, Default" },
    { name = "timestamp", type = "DateTime64(6, 'UTC')", codec = "GCD, Default" },
    { name = "team_id", type = "Int64" },
    { name = "distinct_id", type = "String" },
    { name = "elements_hash", type = "String" },
    { name = "created_at", type = "DateTime64(6, 'UTC')", default_expression = "now()", codec = "GCD, Default" },
    { name = "captured_at", type = "DateTime64(6, 'UTC')", default_expression = "now()", codec = "GCD, Default" },
    { name = "_timestamp", type = "DateTime", codec = "T64, Default" },
    { name = "_offset", type = "UInt64", codec = "T64, Default" },
    { name = "_partition", type = "UInt64", codec = "T64, Default" },
    { name = "elements_chain", type = "String" },
    { name = "elements_chain_href", type = "String", default_expression = "extract(elements_chain, '(?::|\")href=\"(.*?)\"')" },
    { name = "elements_chain_texts", type = "Array(String)", default_expression = "arrayDistinct(extractAll(elements_chain, '(?::|\")text=\"(.*?)\"'))" },
    { name = "elements_chain_elements", type = "Array(Enum8('a' = 1, 'button' = 2, 'form' = 3, 'input' = 4, 'select' = 5, 'textarea' = 6, 'label' = 7))", default_expression = "arrayDistinct(extractAll(elements_chain, '(?:^|;)(a|button|form|input|select|textarea|label)(?:\\.|$|:)'))" },
    { name = "elements_chain_ids", type = "Array(String)", default_expression = "arrayDistinct(extractAll(elements_chain, '(?::|\")attr_id=\"(.*?)\"'))" },
    { name = "person_id", type = "UUID" },
    { name = "properties", type = "JSON(max_dynamic_paths=512, `$browser` LowCardinality(String), `$browser_language` LowCardinality(String), `$browser_version` LowCardinality(String), `$config_defaults` LowCardinality(String), `$device_type` LowCardinality(String), `$exception_functions` Array(String), `$exception_list` Array(JSON(max_dynamic_paths=20, type String, value String)), `$exception_sources` Array(String), `$exception_types` Array(String), `$exception_values` Array(String), `$feature_flags` Map(LowCardinality(String), LowCardinality(String)), `$geoip_city_name` LowCardinality(String), `$geoip_continent_code` LowCardinality(String), `$geoip_continent_name` LowCardinality(String), `$geoip_country_code` LowCardinality(String), `$geoip_country_name` LowCardinality(String), `$geoip_subdivision_1_name` LowCardinality(String), `$geoip_time_zone` LowCardinality(String), `$group_0` String, `$group_1` String, `$group_2` String, `$group_3` String, `$group_4` String, `$lib` LowCardinality(String), `$lib_version` LowCardinality(String), `$mcp_listed_tool_names` Array(String), `$os` LowCardinality(String), `$os_version` LowCardinality(String), `$session_id` String, `$timezone` LowCardinality(String), `$window_id` String)" },
    { name = "temporary_properties", type = "JSON(max_dynamic_paths=64)" },
    { name = "person_properties", type = "JSON(max_dynamic_paths=128, `$browser` LowCardinality(String), `$browser_language` LowCardinality(String), `$browser_version` LowCardinality(String), `$device_type` LowCardinality(String), `$geoip_city_name` LowCardinality(String), `$geoip_continent_code` LowCardinality(String), `$geoip_continent_name` LowCardinality(String), `$geoip_country_code` LowCardinality(String), `$geoip_country_name` LowCardinality(String), `$geoip_subdivision_1_name` LowCardinality(String), `$geoip_time_zone` LowCardinality(String), `$initial_browser` LowCardinality(String), `$initial_browser_language` LowCardinality(String), `$initial_browser_version` LowCardinality(String), `$initial_device_type` LowCardinality(String), `$initial_geoip_city_name` LowCardinality(String), `$initial_geoip_continent_code` LowCardinality(String), `$initial_geoip_continent_name` LowCardinality(String), `$initial_geoip_country_code` LowCardinality(String), `$initial_geoip_country_name` LowCardinality(String), `$initial_geoip_subdivision_1_name` LowCardinality(String), `$initial_geoip_time_zone` LowCardinality(String), `$initial_os` LowCardinality(String), `$initial_os_version` LowCardinality(String), `$os` LowCardinality(String), `$os_version` LowCardinality(String))" },
    { name = "properties_null_keys", type = "Array(LowCardinality(String))" },
    { name = "temporary_properties_null_keys", type = "Array(LowCardinality(String))" },
    { name = "person_properties_null_keys", type = "Array(LowCardinality(String))" },
  ]
}

module "ingest_events_json_historical_mv" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "ingest_events_json_historical_mv")
  database = var.database
  name     = "ingest_events_json_historical_mv"
  override = try(local.deployment.overrides["ingest_events_json_historical_mv"], {})
  to_table = "${var.database}.buffer_events_json_historical"
  query    = <<-SQL
    SELECT * FROM ${var.database}.ingest_events_json WHERE abs(dateDiff('month', toStartOfMonth(timestamp), toStartOfMonth(now()))) > 1
  SQL
}

module "ingest_events_json_recent_mv" {
  source  = "../../lib/materialized_view"
  node    = var.node
  objects = var.objects

  enabled  = contains(var.objects, "ingest_events_json_recent_mv")
  database = var.database
  name     = "ingest_events_json_recent_mv"
  override = try(local.deployment.overrides["ingest_events_json_recent_mv"], {})
  to_table = "${var.database}.buffer_events_json"
  query    = <<-SQL
    SELECT * FROM ${var.database}.ingest_events_json WHERE abs(dateDiff('month', toStartOfMonth(timestamp), toStartOfMonth(now()))) <= 1
  SQL
}
