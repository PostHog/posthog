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
