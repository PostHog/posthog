# Column lists that more than one object uses.

locals {
  web_bot_definition_columns = [
    { name = "id", type = "UInt64" },
    { name = "parent_id", type = "UInt64" },
    { name = "regexp", type = "String" },
    { name = "keys", type = "Array(String)" },
    { name = "values", type = "Array(String)" },
  ]
}
