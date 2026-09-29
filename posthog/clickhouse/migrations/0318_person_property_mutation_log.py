# This migration originally created the person_property_mutation_log pipeline (aux storage table,
# Distributed proxy, Kafka table and MV). It was dropped in 0338 and its SQL definitions removed.
# Left as a no-op so new environments don't create tables that will immediately be dropped.

operations: list = []
