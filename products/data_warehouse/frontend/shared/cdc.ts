// Source types that support change data capture (logical replication). Supabase and Neon
// are Postgres on the wire and reuse the same CDC path. Keep in sync with the backend
// adapter registry in products/warehouse_sources/backend/temporal/data_imports/cdc/adapters.py.
export const CDC_SOURCE_TYPES: string[] = ['Postgres', 'Supabase', 'Neon']
