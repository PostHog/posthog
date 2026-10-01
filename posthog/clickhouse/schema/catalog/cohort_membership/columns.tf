# Column lists that more than one object uses.

locals {
  cohort_membership_columns = [
    { name = "team_id", type = "Int64" },
    { name = "cohort_id", type = "Int64" },
    { name = "person_id", type = "UUID" },
    { name = "status", type = "Enum8('entered' = 1, 'left' = 2)" },
    { name = "last_updated", type = "DateTime64(6)", default_expression = "now64()" },
  ]
}
