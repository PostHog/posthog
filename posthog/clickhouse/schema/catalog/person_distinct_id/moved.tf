moved {
  from = module.person_distinct_id
  to   = module.person_distinct_id_family.module.storage
}

moved {
  from = module.person_distinct_id_mv
  to   = module.person_distinct_id_family.module.mv
}

moved {
  from = module.kafka_person_distinct_id
  to   = module.person_distinct_id_family.module.kafka
}

moved {
  from = module.person_distinct_id2
  to   = module.person_distinct_id2_family.module.storage
}

moved {
  from = module.writable_person_distinct_id2
  to   = module.person_distinct_id2_family.module.write
}

moved {
  from = module.person_distinct_id2_mv
  to   = module.person_distinct_id2_family.module.mv
}

moved {
  from = module.kafka_person_distinct_id2
  to   = module.person_distinct_id2_family.module.kafka
}
