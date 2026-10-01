moved {
  from = module.log_attributes
  to   = module.log_attributes_family.module.storage
}

moved {
  from = module.log_attributes2
  to   = module.log_attributes2_family.module.storage
}

moved {
  from = module.log_attributes3
  to   = module.log_attributes3_family.module.storage
}

moved {
  from = module.log_attributes_distributed
  to   = module.log_attributes3_family.module.read
}

moved {
  from = module.logs32
  to   = module.logs32_family.module.storage
}

moved {
  from = module.logs
  to   = module.logs32_family.module.read
}

moved {
  from = module.logs34
  to   = module.logs34_family.module.storage
}

moved {
  from = module.logs_distributed
  to   = module.logs34_family.module.read
}

moved {
  from = module.writable_logs34
  to   = module.logs34_family.module.write
}

moved {
  from = module.kafka_logs34_avro_mv
  to   = module.logs34_family.module.mv
}

moved {
  from = module.kafka_logs_avro
  to   = module.logs34_family.module.kafka
}

moved {
  from = module.logs_billing_metrics
  to   = module.logs_billing_metrics_family.module.storage
}

moved {
  from = module.logs_billing_metrics_distributed
  to   = module.logs_billing_metrics_family.module.read
}

moved {
  from = module.logs_kafka_metrics
  to   = module.logs_kafka_metrics_family.module.storage
}

moved {
  from = module.logs_kafka_metrics_distributed
  to   = module.logs_kafka_metrics_family.module.read
}

moved {
  from = module.logs_pattern_buckets
  to   = module.logs_pattern_buckets_family.module.storage
}

moved {
  from = module.logs_pattern_buckets_distributed
  to   = module.logs_pattern_buckets_family.module.read
}

moved {
  from = module.logs_volume_buckets
  to   = module.logs_volume_buckets_family.module.storage
}

moved {
  from = module.logs_volume_buckets_distributed
  to   = module.logs_volume_buckets_family.module.read
}
