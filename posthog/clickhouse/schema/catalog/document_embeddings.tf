module "document_embeddings" {
  source     = "./document_embeddings"
  database   = var.database
  deployment = try(var.deployment.families.document_embeddings, { components = [] })
  ttl        = var.ttl
}
