moved {
  from = module.cohort_membership
  to   = module.cohort_membership_family.module.storage
}

moved {
  from = module.writable_cohort_membership
  to   = module.cohort_membership_family.module.write
}

moved {
  from = module.cohort_membership_mv
  to   = module.cohort_membership_family.module.mv
}

moved {
  from = module.kafka_cohort_membership
  to   = module.cohort_membership_family.module.kafka
}
