# Data Warehouse Integration

PostHog's data warehouse integration allows you to connect external data warehouses (BigQuery, Snowflake, Redshift, Databricks) and query them directly alongside PostHog event data.

## Architecture Overview

### Components

1. **WarehouseConnection** (`models/connection.py`)
   - Stores encrypted credentials for warehouse connections
   - Supports three query modes: sync, direct, hybrid
   - Team-scoped with access control

2. **Warehouse Connectors** (`connectors/`)
   - Base connector interface (`base.py`)
   - Provider implementations (BigQuery, Snowflake, etc.)
   - Query execution, schema discovery, cost estimation

3. **Query Executor** (`query_executor.py`)
   - Routes queries to warehouse connectors
   - Handles direct-mode table execution

4. **API Endpoints** (`api/connection.py`)
   - REST API for managing connections
   - Test connections, fetch schemas, estimate costs

### Query Modes

#### Sync Mode (Default)
- Data is copied from warehouse → S3 → ClickHouse
- Queries execute on ClickHouse (fast, consistent)
- Data has sync latency

#### Direct Mode (New)
- Queries execute directly on the warehouse
- Real-time data access
- Uses warehouse compute and costs

#### Hybrid Mode (Future)
- Query results cached in ClickHouse
- Configurable TTL for freshness
- Balance of speed and freshness

## API Usage

### Create Connection
```bash
POST /api/environments/:team_id/warehouse_connections/
{
    "name": "My BigQuery",
    "provider": "bigquery",
    "credentials": {...},
    "mode": "direct"
}
```

### Test Connection
```bash
POST /api/environments/:team_id/warehouse_connections/:id/test/
```

### Get Schema
```bash
GET /api/environments/:team_id/warehouse_connections/:id/schema/
```

### Estimate Query Cost
```bash
POST /api/environments/:team_id/warehouse_connections/:id/estimate_cost/
{
    "sql": "SELECT * FROM large_table"
}
```

## Warehouse Configuration

### BigQuery
Required permissions: `bigquery.jobs.create`, `bigquery.tables.get`, `bigquery.tables.getData`

### Snowflake
Required privileges: `USAGE` on warehouse/database/schema, `SELECT` on tables

## Security

- Credentials encrypted at rest
- Never exposed in API responses (write-only)
- Team-scoped access control
- Read-only credentials recommended
- Query timeouts enforced

## Roadmap

### Phase 1 (MVP) ✅
- [x] Connection management API
- [x] BigQuery & Snowflake connectors
- [x] Direct query execution
- [x] Cost estimation

### Phase 2 (In Progress)
- [ ] HogQL integration
- [ ] Cross-source joins
- [ ] Materialized views

### Phase 3 (Future)
- [ ] More connectors (Redshift, Databricks)
- [ ] Reverse ETL
- [ ] Query cost budgets

For detailed documentation, see TODO/DW_PRODUCT.md and TODO/DW_TODO.md
