variable "host" {
  description = "ClickHouse host."
  type        = string
}

variable "port" {
  description = "ClickHouse native protocol port."
  type        = number
}

variable "protocol" {
  description = "`native` or `nativesecure`."
  type        = string
}

variable "username" {
  description = "ClickHouse user."
  type        = string
}

variable "password" {
  description = "Password of `username`."
  type        = string
  sensitive   = true
}

variable "database" {
  description = "Database the schema is created in. It must exist."
  type        = string
}

variable "kafka" {
  description = "Create the Kafka tables and the materialized views that consume them."
  type        = bool
  default     = true
}

variable "kafka_topic_prefix" {
  description = "Kafka topic prefix, matching the app's KAFKA_PREFIX."
  type        = string
  default     = ""
}

variable "test" {
  description = "Build a test database: no table TTLs, and the materialized views that stand in for the Kafka pipeline."
  type        = bool
  default     = false
}

variable "keeper_path" {
  description = "Complete replication path override for this server, with {table} to isolate each table."
  type        = string
  default     = null
}

variable "dictionary_user" {
  description = "User the dictionaries connect to their source as."
  type        = string
}

variable "dictionary_password" {
  description = "Password of `dictionary_user`."
  type        = string
  sensitive   = true
}
