moved {
  from = module.metric_attributes
  to   = module.metric_attributes_family.module.storage
}

moved {
  from = module.metric_attributes2
  to   = module.metric_attributes2_family.module.storage
}

moved {
  from = module.metric_attributes_distributed
  to   = module.metric_attributes2_family.module.read
}

moved {
  from = module.metric_attributes3
  to   = module.metric_attributes3_family.module.storage
}

moved {
  from = module.metric_names3
  to   = module.metric_names3_family.module.storage
}

moved {
  from = module.metric_samples1
  to   = module.metric_samples1_family.module.storage
}

moved {
  from = module.metric_samples
  to   = module.metric_samples1_family.module.read
}

moved {
  from = module.metric_series1
  to   = module.metric_series1_family.module.storage
}

moved {
  from = module.metric_series
  to   = module.metric_series1_family.module.read
}

moved {
  from = module.metric_series2
  to   = module.metric_series2_family.module.storage
}

moved {
  from = module.metric_series_distributed
  to   = module.metric_series2_family.module.read
}

moved {
  from = module.metric_series3
  to   = module.metric_series3_family.module.storage
}

moved {
  from = module.metrics1
  to   = module.metrics1_family.module.storage
}

moved {
  from = module.metrics
  to   = module.metrics1_family.module.read
}

moved {
  from = module.metrics2
  to   = module.metrics2_family.module.storage
}

moved {
  from = module.metrics_distributed
  to   = module.metrics2_family.module.read
}

moved {
  from = module.metrics4_attributes
  to   = module.metrics4_attributes_family.module.storage
}

moved {
  from = module.writable_metrics4_attributes
  to   = module.metrics4_attributes_family.module.write
}

moved {
  from = module.metrics4_names
  to   = module.metrics4_names_family.module.storage
}

moved {
  from = module.writable_metrics4_names
  to   = module.metrics4_names_family.module.write
}

moved {
  from = module.metrics4_samples
  to   = module.metrics4_samples_family.module.storage
}

moved {
  from = module.writable_metrics4_samples
  to   = module.metrics4_samples_family.module.write
}

moved {
  from = module.metrics4_series
  to   = module.metrics4_series_family.module.storage
}

moved {
  from = module.writable_metrics4_series
  to   = module.metrics4_series_family.module.write
}

moved {
  from = module.metrics_kafka_metrics
  to   = module.metrics_kafka_metrics_family.module.storage
}
