moved {
  from = module.sharded_experiment_exposures_preaggregated
  to   = module.sharded_experiment_exposures_preaggregated_family.module.storage
}

moved {
  from = module.experiment_exposures_preaggregated
  to   = module.sharded_experiment_exposures_preaggregated_family.module.read
}

moved {
  from = module.sharded_experiment_metric_events_preaggregated
  to   = module.sharded_experiment_metric_events_preaggregated_family.module.storage
}

moved {
  from = module.experiment_metric_events_preaggregated
  to   = module.sharded_experiment_metric_events_preaggregated_family.module.read
}
