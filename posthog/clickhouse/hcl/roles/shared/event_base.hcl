# The abstract events core: the column list every copy of the events family shares.
# Its extenders are the sharded storage table and the data node's Distributed proxy
# (roles/data/shared) plus the sessions nodes' replicas of that proxy
# (roles/sessions/shared). It lives here because roles/shared is the one layer every
# role composes, and an abstract emits nothing on a node that does not extend it.
database "posthog" {
  table "_event_base" {
    abstract = true
    column "uuid" {
      type = "UUID"
    }
    column "event" {
      type = "String"
    }
    column "properties" {
      type = "String"
    }
    column "timestamp" {
      type = "DateTime64(6, 'UTC')"
    }
    column "team_id" {
      type = "Int64"
    }
    column "distinct_id" {
      type = "String"
    }
    column "created_at" {
      type = "DateTime64(6, 'UTC')"
    }
    column "$group_0" {
      type = "String"
    }
    column "$group_1" {
      type = "String"
    }
    column "$group_2" {
      type = "String"
    }
    column "$group_3" {
      type = "String"
    }
    column "$group_4" {
      type = "String"
    }
    column "$window_id" {
      type = "String"
    }
    column "$session_id" {
      type = "String"
    }
    column "inserted_at" {
      type    = "Nullable(DateTime64(6, 'UTC'))"
      default = "now64()"
    }
    column "person_mode" {
      type = "Enum8('full'=0, 'propertyless'=1, 'force_upgrade'=2)"
    }
    column "elements_chain_href" {
      type = "String"
    }
    column "elements_chain_texts" {
      type = "Array(String)"
    }
    column "elements_chain_ids" {
      type = "Array(String)"
    }
    column "elements_chain_elements" {
      type = "Array(Enum8('a'=1, 'button'=2, 'form'=3, 'input'=4, 'select'=5, 'textarea'=6, 'label'=7))"
    }
    column "properties_group_custom" {
      type = "Map(String, String)"
    }
    column "properties_group_feature_flags" {
      type = "Map(String, String)"
    }
    column "is_deleted" {
      type = "Bool"
    }
    column "person_properties_map_custom" {
      type = "Map(String, String)"
    }
    column "$session_id_uuid" {
      type = "Nullable(UInt128)"
    }
    column "consumer_breadcrumbs" {
      type = "Array(String)"
    }
    column "properties_group_ai" {
      type = "Map(String, String)"
    }
    column "mat_historical_migration" {
      type = "Nullable(String)"
    }
    column "mat_$ai_session_id" {
      type = "Nullable(String)"
    }
    column "mat_$ai_is_error" {
      type = "Nullable(String)"
    }
    column "dmat_string_0" {
      type = "Nullable(String)"
    }
    column "dmat_string_1" {
      type = "Nullable(String)"
    }
    column "dmat_string_2" {
      type = "Nullable(String)"
    }
    column "dmat_string_3" {
      type = "Nullable(String)"
    }
    column "dmat_string_4" {
      type = "Nullable(String)"
    }
    column "dmat_string_5" {
      type = "Nullable(String)"
    }
    column "dmat_string_6" {
      type = "Nullable(String)"
    }
    column "dmat_string_7" {
      type = "Nullable(String)"
    }
    column "dmat_string_8" {
      type = "Nullable(String)"
    }
    column "dmat_string_9" {
      type = "Nullable(String)"
    }
    column "historical_migration" {
      type = "Bool"
    }
    column "mat_$ai_prompt_name" {
      type = "Nullable(String)"
    }
  }
}
