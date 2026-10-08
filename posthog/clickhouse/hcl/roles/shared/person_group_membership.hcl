database "posthog" {
  table "_person_group_membership" {
    abstract = true

    column "team_id" {
      type = "Int64"
    }
    column "group_type_index" {
      type = "UInt8"
    }
    column "group_key" {
      type = "String"
    }
    column "distinct_id" {
      type = "String"
    }
    column "first_seen" {
      type = "SimpleAggregateFunction(min, DateTime64(6, 'UTC'))"
    }
    column "last_seen" {
      type = "SimpleAggregateFunction(max, DateTime64(6, 'UTC'))"
    }
  }

  table "_person_group_membership_config" {
    abstract = true

    column "team_id" {
      type = "Int64"
    }
    column "group_type_index" {
      type = "UInt8"
    }
    column "enabled" {
      type = "UInt8"
    }
    column "version" {
      type = "UInt64"
    }
  }
}
