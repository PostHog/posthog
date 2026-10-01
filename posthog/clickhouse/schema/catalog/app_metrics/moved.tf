moved {
  from = module.sharded_app_metrics
  to   = module.sharded_app_metrics_family.module.storage
}

moved {
  from = module.app_metrics
  to   = module.sharded_app_metrics_family.module.read
}

moved {
  from = module.writable_app_metrics
  to   = module.sharded_app_metrics_family.module.write
}



moved {
  from = module.sharded_app_metrics2
  to   = module.sharded_app_metrics2_family.module.storage
}

moved {
  from = module.app_metrics2
  to   = module.sharded_app_metrics2_family.module.read
}

moved {
  from = module.writable_app_metrics2
  to   = module.sharded_app_metrics2_family.module.write
}

moved {
  from = module.app_metrics2_mv
  to   = module.sharded_app_metrics2_family.module.mv
}

moved {
  from = module.kafka_app_metrics2
  to   = module.sharded_app_metrics2_family.module.kafka
}
