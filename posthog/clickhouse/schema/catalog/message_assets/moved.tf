moved {
  from = module.message_assets_data
  to   = module.message_assets_data_family.module.storage
}

moved {
  from = module.message_assets
  to   = module.message_assets_data_family.module.read
}

moved {
  from = module.message_assets_mv
  to   = module.message_assets_data_family.module.mv
}

moved {
  from = module.kafka_message_assets
  to   = module.message_assets_data_family.module.kafka
}
