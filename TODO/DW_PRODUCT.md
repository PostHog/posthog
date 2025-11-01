# Data Warehouse Integration Product Plan

## Executive Summary

Enable PostHog customers to bring their own data warehouse (BigQuery, Snowflake, Redshift, Databricks) and seamlessly blend warehouse data with PostHog product analytics on unified dashboards. This transforms PostHog from a standalone analytics platform into the central analytical hub that connects product behavior with business metrics from the entire data stack.

## Current State

PostHog already has foundational data warehouse capabilities:

### Existing Infrastructure
- **HogQL**: Custom SQL dialect that compiles to ClickHouse, supporting complex queries
- **25+ Data Source Integrations**: Including BigQuery, Stripe, Hubspot, Salesforce, etc.
- **Data Sync Architecture**: Temporal workflows sync external data → S3 → queryable tables
- **SQL Editor UI**: Monaco-based editor with syntax highlighting and query execution
- **Unified Query Layer**: Single `Database` class registry for all data sources (events, persons, external tables)
- **Dashboard Integration**: Insights can use HogQL queries, displayable on dashboards
- **Team Isolation**: Built-in multi-tenancy with secure credential storage

### Current Limitations
1. **Sync-Only Model**: External data must be copied to S3/ClickHouse before querying
2. **Limited Push-Down**: Not optimized for querying warehouse directly
3. **No Live Connections**: Can't query warehouse in real-time without sync
4. **Manual Setup**: Requires understanding of data import workflows
5. **Separate Experiences**: Warehouse queries feel distinct from core PostHog analytics
6. **Limited Join Optimization**: Joining warehouse data with event data can be slow
7. **No Write-Back**: Can't send PostHog-computed segments back to warehouse

## Product Vision

### North Star
**"Query your data warehouse as if it were native PostHog data, with insights that blend behavioral and business metrics on the same dashboard."**

### User Value Propositions

#### For Data Teams
- **Single Source of Truth**: PostHog becomes the analytics frontend for the entire data stack
- **Reduced Data Movement**: Option to query warehouse directly vs. syncing
- **Leverage Existing Infrastructure**: Use their existing DW investment and governance
- **Cost Efficiency**: Avoid duplicating large datasets in PostHog storage

#### For Product Teams
- **Complete Context**: See product metrics alongside revenue, support, and operational data
- **Faster Insights**: No waiting for data syncing or ETL pipelines
- **Unified Interface**: One tool instead of switching between PostHog and Looker/Tableau
- **Self-Service**: Query warehouse data without SQL expertise via insight builder

#### For Engineering Teams
- **Less Maintenance**: No custom integrations to keep PostHog and warehouse in sync
- **Better Performance**: Push-down optimization uses warehouse compute power
- **Reverse ETL**: Send computed cohorts back to warehouse for activation

## Product Experience

### Phase 1: Direct Warehouse Connectivity (MVP)

#### Setup Flow
1. **Add Connection** (Settings → Data warehouse → Add connection)
   - Select provider (BigQuery, Snowflake, Redshift, Databricks)
   - Authentication options:
     - Service account JSON (BigQuery)
     - Username/password + endpoint (Snowflake, Redshift)
     - Token + workspace (Databricks)
   - Test connection + show available schemas/tables
   - Configure sync vs. direct query mode per table

2. **Table Configuration**
   - Browse available tables in connected warehouse
   - Preview schema + sample rows
   - Map primary key and timestamp columns
   - Set query mode:
     - **Sync mode**: Import to S3/ClickHouse (current behavior)
     - **Direct mode**: Query warehouse on-demand (new)
     - **Hybrid mode**: Cache in ClickHouse, refresh on schedule (new)
   - Configure refresh schedule for synced/cached tables

3. **Credential Management**
   - Encrypted storage of credentials (existing)
   - Role-based access: which team members can add/edit connections
   - Audit log of connection usage
   - Connection health monitoring + alerts

#### SQL Query Experience
1. **Enhanced SQL Editor**
   - Autocomplete shows both PostHog tables AND warehouse tables
   - Visual indicator of data source (PostHog icon vs. warehouse logo)
   - Query explanation showing which systems will be queried
   - Estimated cost for warehouse queries (BigQuery pricing API)
   - Query history with source attribution

2. **Query Execution**
   - Smart query planning:
     - Pure PostHog queries → ClickHouse only
     - Pure warehouse queries → Warehouse only
     - Cross-source joins → Fetch from warehouse, join in ClickHouse
   - Real-time execution for direct mode
   - Background execution for expensive queries
   - Query timeout configuration per connection
   - Result caching with configurable TTL

3. **Performance Optimization**
   - **Predicate Push-Down**: WHERE clauses execute in warehouse
   - **Projection Push-Down**: SELECT only needed columns
   - **Partition Pruning**: Leverage warehouse partitioning
   - **Query Rewriting**: Optimize cross-source joins
   - **Cost Estimation**: Warn before expensive queries

#### Dashboard Integration
1. **Unified Insights**
   - Create insights from warehouse queries (SQL-based)
   - Mix PostHog trends/funnels with warehouse SQL on same dashboard
   - Dashboard filters apply to compatible warehouse queries
   - Consistent styling and formatting across sources

2. **Example Use Cases**
   ```
   Dashboard: "Product-Led Growth Overview"
   - Tile 1: Weekly active users (PostHog events)
   - Tile 2: Trial conversions (PostHog funnel)
   - Tile 3: Revenue by cohort (Warehouse: transactions table)
   - Tile 4: Customer health score (Warehouse: joined Salesforce + usage)
   - Tile 5: Feature adoption vs. NPS (Join PostHog events + warehouse surveys)
   ```

3. **Filter Compatibility**
   - Date range filters apply to warehouse timestamp columns
   - Property filters work when warehouse has matching columns
   - Cohort filters: option to sync cohort to warehouse for filtering

### Phase 2: Advanced Integration

#### Insight Builder for Warehouse Data
1. **No-Code Query Builder**
   - Select warehouse table as data source in insight creation
   - Visual query builder (like Metabase/Mode):
     - Select columns
     - Add filters (where clauses)
     - Group by + aggregations
     - Order by + limit
   - Generates HogQL behind the scenes
   - Supports trends, bar charts, tables (not funnels initially)

2. **Cross-Source Insights**
   - Join events with warehouse tables:
     - Example: "Page views WHERE user_id IN (SELECT id FROM warehouse.premium_users)"
   - Join persons with warehouse enrichment:
     - Example: "Show MRR breakdown by signup UTM source"
   - Performance warnings when joins will be slow

#### Materialized Views & Incremental Updates
1. **Warehouse → PostHog Materialization**
   - Schedule warehouse queries to refresh ClickHouse tables
   - Incremental updates: track high water mark, only fetch new rows
   - Conflict resolution for updates/deletes
   - Status dashboard showing sync health

2. **PostHog → Warehouse Write-Back**
   - Export computed cohorts to warehouse tables
   - Reverse ETL for activation:
     - "Export trial users who activated feature X → warehouse.activated_users"
     - Use in warehouse queries, BI tools, or activation platforms
   - Scheduled exports with incremental updates

#### Semantic Layer
1. **Unified Metrics Definitions**
   - Define metrics once, use everywhere:
     ```yaml
     metrics:
       - name: "Active Users"
         source: posthog.events
         query: "COUNT(DISTINCT person_id) WHERE event='$pageview'"

       - name: "Monthly Revenue"
         source: warehouse.stripe_charges
         query: "SUM(amount) WHERE status='succeeded'"
     ```
   - Metrics available in insight builder as pre-defined calculations
   - Version control for metric definitions

2. **Virtual Tables**
   - Define joined tables in config, query as if native:
     ```yaml
     virtual_tables:
       - name: "enriched_users"
         query: |
           SELECT
             ph.person_id,
             ph.distinct_id,
             dw.subscription_tier,
             dw.mrr
           FROM posthog.persons ph
           LEFT JOIN warehouse.customers dw ON ph.email = dw.email
     ```
   - Appears in database registry, queryable via HogQL
   - Cached with configurable refresh

### Phase 3: Enterprise Features

#### Advanced Security & Governance
1. **Column-Level Access Control**
   - Restrict sensitive warehouse columns by role
   - Row-level security: filter warehouse queries by user properties
   - Query approval workflows for production connections
   - PII detection and masking

2. **Compliance & Audit**
   - Query audit log with user attribution
   - Data lineage: track which dashboards use which warehouse tables
   - Cost attribution: charge back query costs to teams/users
   - GDPR/CCPA: propagate deletion requests to warehouse

#### Query Optimization & Cost Management
1. **Query Acceleration**
   - Automatic result caching with smart invalidation
   - Query result pre-fetching for scheduled dashboards
   - Aggregation push-down to warehouse compute
   - Query federation: parallel execution across multiple warehouses

2. **Cost Controls**
   - Set budget limits per connection/team
   - Pause expensive queries + require approval
   - Cost dashboards showing spend by team/user/dashboard
   - Optimization recommendations (e.g., "Add index on X")

#### Multi-Warehouse Federation
1. **Query Across Warehouses**
   - Connect multiple warehouses simultaneously
   - Cross-warehouse joins:
     - Example: BigQuery customers JOIN Snowflake transactions
   - Smart routing: move small table to large table's warehouse
   - Result caching to avoid repeated cross-warehouse queries

2. **Warehouse Selection**
   - Default warehouse per team
   - Override warehouse in SQL: `FROM bigquery.customers`
   - Load balancing across warehouse replicas

## Technical Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                       Frontend (React)                       │
├─────────────────────────────────────────────────────────────┤
│  SQL Editor  │  Insight Builder  │  Dashboard Renderer      │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                    PostHog API (Django)                      │
├─────────────────────────────────────────────────────────────┤
│  Query API  │  Warehouse API  │  Connection Management      │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                   HogQL Query Planner                        │
├─────────────────────────────────────────────────────────────┤
│  • Parse HogQL query                                        │
│  • Identify data sources (PostHog, BigQuery, Snowflake)     │
│  • Generate execution plan                                  │
│  • Apply optimizations (push-down, caching)                 │
└─────────────────────────────────────────────────────────────┘
                            │
            ┌───────────────┼───────────────┐
            ▼               ▼               ▼
    ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
    │ ClickHouse  │  │  BigQuery   │  │  Snowflake  │
    │  (PostHog)  │  │ Connector   │  │  Connector  │
    └─────────────┘  └─────────────┘  └─────────────┘
```

### Query Execution Strategies

#### Strategy 1: Sync Mode (Current)
```
Warehouse → Temporal → S3 → ClickHouse → HogQL Query → Results
```
**Pros**: Fast queries, consistent experience, offline if warehouse down
**Cons**: Data latency, storage costs, ETL overhead

#### Strategy 2: Direct Query Mode (New - MVP)
```
HogQL Query → Warehouse Connector → Warehouse → Results
```
**Pros**: Real-time data, no sync lag, lower storage costs
**Cons**: Query latency, warehouse costs, dependency on warehouse uptime

#### Strategy 3: Hybrid Mode (New - Phase 2)
```
HogQL Query → Check Cache → If miss: Warehouse Query → Cache → Results
```
**Pros**: Balance of freshness and speed
**Cons**: Complexity, cache invalidation challenges

#### Strategy 4: Federated Query (New - Phase 2)
```
HogQL Query → Split query →
  • PostHog subquery → ClickHouse
  • Warehouse subquery → Warehouse
  → Join in ClickHouse → Results
```
**Pros**: Leverage both systems' strengths
**Cons**: Network overhead, complex optimization

### Component Design

#### 1. Warehouse Connector Layer
```python
# /posthog/warehouse/connectors/base.py
class BaseWarehouseConnector(ABC):
    """Abstract base for warehouse connectors"""

    @abstractmethod
    def execute_query(self, sql: str, params: dict) -> QueryResult:
        """Execute SQL query on warehouse"""
        pass

    @abstractmethod
    def get_schema(self) -> List[TableSchema]:
        """Retrieve available tables and columns"""
        pass

    @abstractmethod
    def estimate_cost(self, sql: str) -> Cost:
        """Estimate query cost before execution"""
        pass

    @abstractmethod
    def supports_push_down(self) -> PushDownCapabilities:
        """Declare which optimizations are supported"""
        pass
```

**Implementations**:
- `BigQueryConnector`: Use google-cloud-bigquery SDK
- `SnowflakeConnector`: Use snowflake-connector-python
- `RedshiftConnector`: Use psycopg2 (Postgres protocol)
- `DatabricksConnector`: Use databricks-sql-connector

#### 2. Query Planner
```python
# /posthog/hogql/warehouse/query_planner.py
class WarehouseQueryPlanner:
    """Analyze HogQL and generate execution plan"""

    def plan(self, query: HogQLQuery, context: QueryContext) -> ExecutionPlan:
        # 1. Parse query AST
        # 2. Identify table sources (PostHog vs warehouse)
        # 3. Analyze joins and filters
        # 4. Choose execution strategy
        # 5. Apply optimizations
        # 6. Generate execution plan
        pass
```

**Execution Plans**:
- `SingleSourcePlan`: Query only ClickHouse or only warehouse
- `FederatedPlan`: Query multiple sources, join results
- `CachedPlan`: Return cached results if available

#### 3. Query Optimizer
```python
# /posthog/hogql/warehouse/optimizer.py
class WarehouseQueryOptimizer:
    """Apply optimizations for warehouse queries"""

    def optimize(self, plan: ExecutionPlan) -> ExecutionPlan:
        # Predicate push-down
        # Projection push-down
        # Partition pruning
        # Join reordering
        # Caching opportunities
        pass
```

**Optimizations**:
- **Predicate Push-Down**: Move WHERE clauses to warehouse execution
- **Projection Push-Down**: SELECT only needed columns from warehouse
- **Aggregation Push-Down**: Compute SUM/COUNT in warehouse, not PostHog
- **Partition Pruning**: Leverage warehouse partitioning (e.g., date ranges)
- **Join Optimization**: Move small table to large table's location

#### 4. Connection Manager
```python
# /posthog/warehouse/models/connection.py
class WarehouseConnection(Model):
    """Store warehouse connection credentials"""
    team = ForeignKey(Team)
    name = CharField()
    provider = CharField(choices=[BIGQUERY, SNOWFLAKE, ...])
    credentials = EncryptedJSONField()  # Encrypted at rest
    mode = CharField(choices=[SYNC, DIRECT, HYBRID])
    is_active = BooleanField()
    config = JSONField()  # Timeout, cache TTL, etc.
    created_by = ForeignKey(User)

    def test_connection(self) -> ConnectionTestResult:
        """Validate credentials and connectivity"""
        pass

    def get_connector(self) -> BaseWarehouseConnector:
        """Return appropriate connector instance"""
        pass
```

#### 5. Cache Layer
```python
# /posthog/warehouse/cache.py
class WarehouseQueryCache:
    """Cache warehouse query results"""

    def get(self, query: str, connection_id: int) -> Optional[QueryResult]:
        # Check Redis/ClickHouse for cached results
        pass

    def set(self, query: str, connection_id: int, result: QueryResult, ttl: int):
        # Store results with TTL
        pass

    def invalidate(self, connection_id: int, tables: List[str]):
        # Invalidate cache when tables updated
        pass
```

**Caching Strategies**:
- **Query-based**: Cache entire query result (for repeated dashboards)
- **Table-based**: Cache table scans, reuse for different queries
- **Incremental**: Cache base query, append new data
- **TTL-based**: Expire after configured duration
- **Event-based**: Invalidate on warehouse table updates

### Security Architecture

#### Credential Storage
```python
# Encrypted in database
class WarehouseConnection:
    credentials = EncryptedJSONField(
        encryption_key=settings.WAREHOUSE_CREDENTIALS_KEY
    )
```

#### Access Control
```python
# Team-level isolation
class WarehouseConnectionViewSet:
    def get_queryset(self):
        return WarehouseConnection.objects.filter(team=self.request.team)
```

#### Query Sandboxing
- Warehouse connections use read-only credentials
- No DDL allowed (CREATE, DROP, ALTER)
- Query timeout enforcement
- Resource limit configuration

#### Audit Logging
```python
class WarehouseQueryLog(Model):
    team = ForeignKey(Team)
    user = ForeignKey(User)
    connection = ForeignKey(WarehouseConnection)
    query = TextField()
    executed_at = DateTimeField(auto_now_add=True)
    duration_ms = IntegerField()
    bytes_processed = BigIntegerField()
    cost = DecimalField()
```

## UX Design Considerations

### Setup Wizard
- **Connection Test**: Real-time validation with helpful error messages
- **Sample Queries**: Show example queries customer can run immediately
- **Estimated Costs**: Warn about potential warehouse query costs upfront
- **Guided Configuration**: Default to safe settings, explain advanced options

### SQL Editor Enhancements
- **Source Badges**: Visual indicator showing which tables come from which warehouse
- **Query Explanation**: "This query will scan BigQuery (est. $0.05) and join in PostHog"
- **Cost Warnings**: "This query will scan 10TB, estimated cost $50. Continue?"
- **Smart Autocomplete**: Show relevant tables based on query context
- **Query Templates**: Pre-built queries for common warehouse use cases

### Dashboard Experience
- **Loading States**: Show which tiles are loading from warehouse vs. cached
- **Error Handling**: Graceful degradation if warehouse unavailable
- **Refresh Controls**: Manual refresh button for warehouse-backed tiles
- **Cost Attribution**: Show per-tile query costs on hover (optional)

### Performance Indicators
- **Query Speed**: Show execution time per data source
- **Cache Status**: Indicate if results are cached or fresh
- **Warehouse Health**: Status indicator for each connected warehouse
- **Cost Dashboard**: Track warehouse query spend over time

## Success Metrics

### Adoption Metrics
- % of teams with warehouse connection
- % of dashboards with warehouse-backed insights
- Number of warehouse queries executed per week
- DAU/MAU of SQL editor

### Performance Metrics
- P50/P95 query latency (warehouse vs. PostHog)
- Cache hit rate for warehouse queries
- Query failure rate by warehouse provider
- Data freshness (lag between warehouse and PostHog view)

### Value Metrics
- Time saved vs. building custom integrations
- Reduction in duplicated data storage
- NPS among warehouse integration users
- Revenue from upsells (enterprise warehouse features)

## Go-to-Market Strategy

### Positioning
- **Primary Message**: "One analytics platform for your entire data stack"
- **Target Personas**:
  - Data teams at companies with existing warehouse investment
  - Product teams frustrated by switching between tools
  - Engineering teams maintaining custom PostHog ↔ warehouse integrations

### Pricing Strategy
- **Inclusion**:
  - Basic warehouse connectivity (1-2 connections): Free/Growth tier
  - SQL editor + dashboard integration: Free/Growth tier
  - Sync mode (current behavior): Free/Growth tier
- **Premium Features**:
  - Direct query mode: Enterprise tier
  - Unlimited connections: Enterprise tier
  - Advanced security (RBAC, audit logs): Enterprise tier
  - Query cost management: Enterprise tier
  - Semantic layer: Enterprise tier

### Launch Plan
**Beta (Month 1-2)**:
- Invite 10-20 existing customers with warehouse + PostHog usage
- Focus on BigQuery (most common), Snowflake (enterprise)
- Gather feedback on setup flow, query performance, dashboard experience
- Iterate on UX based on real usage patterns

**GA (Month 3)**:
- Launch Phase 1 (Direct connectivity + SQL querying)
- Blog post + demo video
- Docs: Setup guides per warehouse, example queries, troubleshooting
- Customer webinar series

**Phase 2 (Month 6)**:
- Launch Insight builder for warehouse data
- Launch Materialized views + write-back
- Case studies from beta customers

**Phase 3 (Month 12)**:
- Launch Enterprise features
- Multi-warehouse federation
- Semantic layer

## Risk Mitigation

### Technical Risks
| Risk | Mitigation |
|------|------------|
| Warehouse query performance unpredictable | Show cost/time estimates, enforce timeouts, cache aggressively |
| Cross-source joins are slow | Intelligent query planning, materialization for common joins, clear UX expectations |
| Warehouse credentials security | Encryption at rest, server-side only, audit logging, read-only access |
| Warehouse API rate limits | Exponential backoff, query queuing, warn users in UI |
| HogQL → Warehouse SQL translation complexity | Start with passthrough SQL, incrementally add HogQL features per warehouse |

### Business Risks
| Risk | Mitigation |
|------|------------|
| Low adoption (too complex) | Invest in setup wizard UX, comprehensive docs, customer success support |
| High support burden | Proactive error messages, self-serve troubleshooting guides, connection health monitoring |
| Warehouse costs blamed on PostHog | Transparent cost estimation, user confirmation for expensive queries, cost dashboards |
| Cannibalize event ingestion revenue | Position as complementary, not replacement. Warehouse for business data, PostHog for behavioral. |

## Open Questions

1. **Query Timeout Defaults**: What's reasonable per warehouse type?
2. **Cache TTL**: How long should warehouse query results be cached by default?
3. **Join Limits**: Should we limit cross-source join sizes to prevent OOM?
4. **Credential Rotation**: How often should customers rotate warehouse credentials?
5. **Warehouse → PostHog Cohorts**: Should synced cohorts auto-update or require manual refresh?
6. **Query Cost Visibility**: Show estimated costs before query execution? Only for queries over $X?
7. **Multi-Tenancy**: Can warehouse connections be shared across teams in org?

## Appendix: Competitor Analysis

### Existing Solutions
- **Mode/Hex/Metabase**: Query warehouses with SQL, create dashboards. No behavioral analytics integration.
- **Amplitude/Mixpanel**: Product analytics only, no warehouse connectivity.
- **Looker**: Strong warehouse integration, but expensive and complex. Weak on behavioral analytics.
- **GoodData**: Embedded analytics platform with warehouse connectors, but no product analytics.

### PostHog Differentiation
- **Unified Experience**: Behavioral + warehouse data in same dashboard
- **Developer-First**: SQL editor + HogQL vs. drag-and-drop limitations
- **Open Source**: Self-host with full warehouse control
- **Product-Led**: Easy setup, fast time-to-value
- **Flexible Deployment**: Cloud or self-hosted with same features

---

**Document Version**: 1.0
**Last Updated**: 2025-10-28
**Owner**: Product Team
**Status**: Planning
