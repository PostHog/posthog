moved {
  from = module.sharded_conversion_goal_attributed_preaggregated
  to   = module.sharded_conversion_goal_attributed_preaggregated_family.module.storage
}

moved {
  from = module.conversion_goal_attributed_preaggregated
  to   = module.sharded_conversion_goal_attributed_preaggregated_family.module.read
}

moved {
  from = module.sharded_marketing_conversions_preaggregated
  to   = module.sharded_marketing_conversions_preaggregated_family.module.storage
}

moved {
  from = module.marketing_conversions_preaggregated
  to   = module.sharded_marketing_conversions_preaggregated_family.module.read
}

moved {
  from = module.sharded_marketing_costs_preaggregated
  to   = module.sharded_marketing_costs_preaggregated_family.module.storage
}

moved {
  from = module.marketing_costs_preaggregated
  to   = module.sharded_marketing_costs_preaggregated_family.module.read
}

moved {
  from = module.sharded_marketing_touchpoints_preaggregated
  to   = module.sharded_marketing_touchpoints_preaggregated_family.module.storage
}

moved {
  from = module.marketing_touchpoints_preaggregated
  to   = module.sharded_marketing_touchpoints_preaggregated_family.module.read
}
