# Resolver tags. A LazyJoin stores one of these (plus JSON-able `resolver_params`) instead of
# a Python closure, so a join is described as plain, serializable data. The tag → implementation
# mapping lives in `lazy_join_registry.RESOLVERS` — every supported tag must be listed there.
# This module is import-dependency-free so any module can reference tags without import cycles.
FOREIGN_KEY = "foreign_key"
DATA_WAREHOUSE = "data_warehouse"
DATA_WAREHOUSE_EXPERIMENTS = "data_warehouse_experiments"
