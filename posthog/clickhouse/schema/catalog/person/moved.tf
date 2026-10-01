moved {
  from = module.person
  to   = module.person_family.module.storage
}

moved {
  from = module.writable_person
  to   = module.person_family.module.write
}

moved {
  from = module.person_mv
  to   = module.person_family.module.mv
}

moved {
  from = module.kafka_person
  to   = module.person_family.module.kafka
}
