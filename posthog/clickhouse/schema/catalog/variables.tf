variable "database" {
  type    = string
  default = "posthog"
}

variable "deployment" {
  description = "Default placement for each layout, plus explicit per-family differences. Each family's deployment is validated by table_family."
  type = object({
    sharded  = any
    global   = any
    families = optional(any, {})
  })
}

variable "ttl" {
  type    = bool
  default = true
}
variable "dictionary_user" {
  type    = string
  default = "default"
}
variable "dictionary_password" {
  type      = string
  default   = ""
  sensitive = true
}
