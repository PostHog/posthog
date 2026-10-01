moved {
  from = module.groups
  to   = module.groups_family.module.storage
}

moved {
  from = module.writable_groups
  to   = module.groups_family.module.write
}

moved {
  from = module.groups_mv
  to   = module.groups_family.module.mv
}

moved {
  from = module.kafka_groups
  to   = module.groups_family.module.kafka
}
