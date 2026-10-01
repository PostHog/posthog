moved {
  from = module.sharded_preaggregation_results
  to   = module.sharded_preaggregation_results_family.module.storage
}

moved {
  from = module.preaggregation_results
  to   = module.sharded_preaggregation_results_family.module.read
}
