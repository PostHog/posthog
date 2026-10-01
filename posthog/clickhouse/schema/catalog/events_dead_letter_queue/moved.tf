moved {
  from = module.events_dead_letter_queue
  to   = module.events_dead_letter_queue_family.module.storage
}

moved {
  from = module.writable_events_dead_letter_queue
  to   = module.events_dead_letter_queue_family.module.write
}

moved {
  from = module.events_dead_letter_queue_mv
  to   = module.events_dead_letter_queue_family.module.mv
}

moved {
  from = module.kafka_events_dead_letter_queue
  to   = module.events_dead_letter_queue_family.module.kafka
}
