module "events_dead_letter_queue" {
  source     = "./events_dead_letter_queue"
  database   = var.database
  deployment = try(var.deployment.families.events_dead_letter_queue, { components = [] })
  ttl        = var.ttl
}
