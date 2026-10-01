module "session_replay" {
  source     = "./session_replay"
  database   = var.database
  deployment = try(var.deployment.families.session_replay, { components = [] })
  ttl        = var.ttl
}
