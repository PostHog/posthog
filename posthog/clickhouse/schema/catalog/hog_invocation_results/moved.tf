moved {
  from = module.hog_invocation_results_data
  to   = module.hog_invocation_results_data_family.module.storage
}

moved {
  from = module.hog_invocation_results
  to   = module.hog_invocation_results_data_family.module.read
}

moved {
  from = module.hog_invocation_results_mv
  to   = module.hog_invocation_results_data_family.module.mv
}

moved {
  from = module.kafka_hog_invocation_results
  to   = module.hog_invocation_results_data_family.module.kafka
}
