module "pg_embeddings" {
  source     = "./pg_embeddings"
  database   = var.database
  deployment = try(var.deployment.families.pg_embeddings, { components = [] })
}
