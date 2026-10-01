variable "database" {
  description = "Database the objects live in."
  type        = string
  default     = "posthog"
}

variable "dictionary_user" {
  description = "User the dictionaries connect to their source as."
  type        = string
  default     = "default"
}

variable "dictionary_password" {
  description = "Password of `dictionary_user`."
  type        = string
  default     = ""
  sensitive   = true
}

variable "deployment" { type = any }
