moved {
  from = module.trace_attributes
  to   = module.trace_attributes_family.module.storage
}

moved {
  from = module.trace_attributes_distributed
  to   = module.trace_attributes_family.module.read
}

moved {
  from = module.trace_attributes2
  to   = module.trace_attributes2_family.module.storage
}

moved {
  from = module.trace_spans
  to   = module.trace_spans_family.module.storage
}

moved {
  from = module.trace_spans_distributed
  to   = module.trace_spans_family.module.read
}

moved {
  from = module.kafka_trace_spans_avro_mv
  to   = module.trace_spans_family.module.mv
}

moved {
  from = module.kafka_trace_spans_avro
  to   = module.trace_spans_family.module.kafka
}

moved {
  from = module.trace_spans_kafka_metrics
  to   = module.trace_spans_kafka_metrics_family.module.storage
}
