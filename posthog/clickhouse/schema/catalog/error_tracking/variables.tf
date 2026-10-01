variable "database" {
  description = "Database the objects live in."
  type        = string
  default     = "posthog"
}

variable "deployment" { type = any }
