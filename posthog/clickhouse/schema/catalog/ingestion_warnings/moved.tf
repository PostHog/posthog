moved {
  from = module.ingestion_warnings_v2
  to   = module.ingestion_warnings_v2_family.module.storage
}

moved {
  from = module.ingestion_warnings_v2_distributed
  to   = module.ingestion_warnings_v2_family.module.read
}

moved {
  from = module.ingestion_warnings_v2_mv
  to   = module.ingestion_warnings_v2_family.module.mv
}

moved {
  from = module.kafka_ingestion_warnings_v2
  to   = module.ingestion_warnings_v2_family.module.kafka
}

moved {
  from = module.sharded_ingestion_warnings
  to   = module.sharded_ingestion_warnings_family.module.storage
}

moved {
  from = module.ingestion_warnings
  to   = module.sharded_ingestion_warnings_family.module.read
}

moved {
  from = module.writable_ingestion_warnings
  to   = module.sharded_ingestion_warnings_family.module.write
}
