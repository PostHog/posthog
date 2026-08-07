# NOTE: this migration previously created `kafka_cohort_membership_ws` and
# `cohort_membership_ws_mv` — a WarpStream Kafka engine table on the
# `warpstream_calculated_events` named collection plus its materialized view.
#
# The `cohort_membership_changed` topic no longer has a producer and the
# warpstream-calculated-events cluster is being decommissioned, so migration 0293
# drops both objects and their SQL definitions have been removed from
# `posthog/models/cohortmembership/sql.py`. Creating them here only for 0293 to
# drop them again would be pointless, so this migration is now a no-op.
# Environments that already ran it keep their recorded migration row and pick up
# the drop from 0293.

operations = []
