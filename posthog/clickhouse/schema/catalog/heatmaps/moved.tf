moved {
  from = module.sharded_heatmaps
  to   = module.sharded_heatmaps_family.module.storage
}

moved {
  from = module.heatmaps
  to   = module.sharded_heatmaps_family.module.read
}

moved {
  from = module.writable_heatmaps
  to   = module.sharded_heatmaps_family.module.write
}

moved {
  from = module.heatmaps_mv
  to   = module.sharded_heatmaps_family.module.mv
}

moved {
  from = module.kafka_heatmaps
  to   = module.sharded_heatmaps_family.module.kafka
}
