# :KLUDGE: The original migration updated person_distinct_id in ways new installs don't need to.
#   Also this migration fails due to repeated zk paths when replicated.
#   Given this, skip this migration
operations = []  # type: ignore
