moved {
  from = module.property_values
  to   = module.property_values_family.module.storage
}

moved {
  from = module.property_values_distributed
  to   = module.property_values_family.module.read
}

moved {
  from = module.property_values_mv
  to   = module.property_values_family.module.mv
}

moved {
  from = module.kafka_property_values
  to   = module.property_values_family.module.kafka
}
