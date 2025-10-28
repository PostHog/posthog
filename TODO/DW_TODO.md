# Data Warehouse Integration - Technical TODO

## Overview

This document outlines the technical implementation tasks for enhancing PostHog's data warehouse integration. Tasks are organized by priority (MVP → Phase 2 → Phase 3) and component area.

**Current State**: PostHog has existing warehouse integration via sync mode (Temporal → S3 → ClickHouse). This plan extends it with direct querying, better UX, and advanced features.

## Task Organization

- **P0**: Must have for MVP (direct warehouse querying)
- **P1**: Phase 2 (enhanced UX, materialization)
- **P2**: Phase 3 (enterprise features)
- **Status**: 🟢 Done | 🟡 In Progress | ⚪ Not Started

---

## MVP: Direct Warehouse Connectivity

### Backend - Warehouse Connectors (P0)

#### Task 1.1: Create Base Connector Interface ⚪
**File**: `/posthog/warehouse/connectors/base.py`

```python
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any
from dataclasses import dataclass

@dataclass
class QueryResult:
    rows: List[Dict[str, Any]]
    columns: List[str]
    execution_time_ms: int
    bytes_processed: int
    cached: bool

@dataclass
class TableSchema:
    name: str
    columns: List[ColumnSchema]
    row_count: Optional[int]
    size_bytes: Optional[int]

@dataclass
class ColumnSchema:
    name: str
    type: str
    nullable: bool

@dataclass
class QueryCost:
    estimated_bytes: int
    estimated_cost_usd: float
    warning_message: Optional[str]

@dataclass
class PushDownCapabilities:
    supports_predicate: bool
    supports_projection: bool
    supports_aggregation: bool
    supports_limit: bool
    supports_join: bool

class BaseWarehouseConnector(ABC):
    """Abstract base class for warehouse connectors"""

    def __init__(self, connection: 'WarehouseConnection'):
        self.connection = connection
        self.credentials = connection.get_decrypted_credentials()
        self.config = connection.config

    @abstractmethod
    def execute_query(self, sql: str, params: Optional[Dict] = None) -> QueryResult:
        """Execute SQL query on warehouse"""
        pass

    @abstractmethod
    def get_schema(self, schema_name: Optional[str] = None) -> List[TableSchema]:
        """Retrieve available tables and columns"""
        pass

    @abstractmethod
    def estimate_cost(self, sql: str) -> QueryCost:
        """Estimate query cost before execution"""
        pass

    @abstractmethod
    def test_connection(self) -> bool:
        """Test if connection credentials are valid"""
        pass

    def supports_push_down(self) -> PushDownCapabilities:
        """Declare which optimizations are supported"""
        return PushDownCapabilities(
            supports_predicate=True,
            supports_projection=True,
            supports_aggregation=False,
            supports_limit=True,
            supports_join=False,
        )

    def get_timeout(self) -> int:
        """Get query timeout in seconds"""
        return self.config.get('timeout_seconds', 300)
```

**Dependencies**: None
**Testing**: Unit tests for base class methods

---

#### Task 1.2: Implement BigQuery Connector ⚪
**File**: `/posthog/warehouse/connectors/bigquery.py`

```python
from google.cloud import bigquery
from google.oauth2 import service_account
from .base import BaseWarehouseConnector, QueryResult, TableSchema, QueryCost

class BigQueryConnector(BaseWarehouseConnector):
    """Google BigQuery connector"""

    def __init__(self, connection):
        super().__init__(connection)
        credentials = service_account.Credentials.from_service_account_info(
            self.credentials['service_account_json']
        )
        self.client = bigquery.Client(
            credentials=credentials,
            project=self.credentials['project_id']
        )

    def execute_query(self, sql: str, params=None) -> QueryResult:
        job_config = bigquery.QueryJobConfig(
            use_query_cache=True,
            timeout=self.get_timeout()
        )
        query_job = self.client.query(sql, job_config=job_config)
        result = query_job.result()

        return QueryResult(
            rows=[dict(row) for row in result],
            columns=[field.name for field in result.schema],
            execution_time_ms=int(query_job.ended - query_job.started).total_seconds() * 1000,
            bytes_processed=query_job.total_bytes_processed,
            cached=query_job.cache_hit,
        )

    def get_schema(self, schema_name=None) -> List[TableSchema]:
        dataset_id = schema_name or self.credentials.get('default_dataset')
        dataset = self.client.get_dataset(dataset_id)
        tables = self.client.list_tables(dataset)

        schemas = []
        for table in tables:
            full_table = self.client.get_table(table.reference)
            schemas.append(TableSchema(
                name=f"{dataset_id}.{table.table_id}",
                columns=[
                    ColumnSchema(
                        name=field.name,
                        type=field.field_type,
                        nullable=field.mode == 'NULLABLE'
                    )
                    for field in full_table.schema
                ],
                row_count=full_table.num_rows,
                size_bytes=full_table.num_bytes,
            ))
        return schemas

    def estimate_cost(self, sql: str) -> QueryCost:
        # BigQuery dry run to estimate bytes scanned
        job_config = bigquery.QueryJobConfig(dry_run=True)
        query_job = self.client.query(sql, job_config=job_config)

        bytes_scanned = query_job.total_bytes_processed
        # BigQuery pricing: $5 per TB
        cost_usd = (bytes_scanned / 1_000_000_000_000) * 5

        warning = None
        if cost_usd > 1.0:
            warning = f"This query will scan {bytes_scanned / 1e9:.2f} GB and cost ~${cost_usd:.2f}"

        return QueryCost(
            estimated_bytes=bytes_scanned,
            estimated_cost_usd=cost_usd,
            warning_message=warning,
        )

    def test_connection(self) -> bool:
        try:
            self.client.query("SELECT 1").result()
            return True
        except Exception:
            return False
```

**Dependencies**: `google-cloud-bigquery` package
**Testing**: Integration tests with BigQuery emulator or test project
**Files to Reference**:
- `/posthog/warehouse/data_load/source/bigquery.py` (existing BigQuery sync source)

---

#### Task 1.3: Implement Snowflake Connector ⚪
**File**: `/posthog/warehouse/connectors/snowflake.py`

```python
import snowflake.connector
from .base import BaseWarehouseConnector, QueryResult, TableSchema, QueryCost

class SnowflakeConnector(BaseWarehouseConnector):
    """Snowflake connector"""

    def __init__(self, connection):
        super().__init__(connection)
        self.conn = snowflake.connector.connect(
            user=self.credentials['username'],
            password=self.credentials['password'],
            account=self.credentials['account'],
            warehouse=self.credentials.get('warehouse'),
            database=self.credentials.get('database'),
            schema=self.credentials.get('schema'),
            timeout=self.get_timeout(),
        )

    def execute_query(self, sql: str, params=None) -> QueryResult:
        import time
        cursor = self.conn.cursor()
        start = time.time()
        cursor.execute(sql, params or {})
        rows = cursor.fetchall()
        execution_time = (time.time() - start) * 1000

        columns = [desc[0] for desc in cursor.description]

        return QueryResult(
            rows=[dict(zip(columns, row)) for row in rows],
            columns=columns,
            execution_time_ms=int(execution_time),
            bytes_processed=0,  # Snowflake doesn't expose this easily
            cached=False,  # Could check query result cache
        )

    def get_schema(self, schema_name=None) -> List[TableSchema]:
        schema = schema_name or self.credentials.get('schema')
        cursor = self.conn.cursor()
        cursor.execute(f"SHOW TABLES IN SCHEMA {schema}")
        tables = cursor.fetchall()

        schemas = []
        for table in tables:
            table_name = table[1]  # Table name is second column
            cursor.execute(f"DESCRIBE TABLE {schema}.{table_name}")
            columns_info = cursor.fetchall()

            schemas.append(TableSchema(
                name=f"{schema}.{table_name}",
                columns=[
                    ColumnSchema(
                        name=col[0],
                        type=col[1],
                        nullable=col[3] == 'Y'
                    )
                    for col in columns_info
                ],
                row_count=None,  # Would need separate query
                size_bytes=None,
            ))
        return schemas

    def estimate_cost(self, sql: str) -> QueryCost:
        # Snowflake doesn't provide easy cost estimation
        # Could use EXPLAIN to estimate rows scanned
        return QueryCost(
            estimated_bytes=0,
            estimated_cost_usd=0.0,
            warning_message="Cost estimation not available for Snowflake",
        )

    def test_connection(self) -> bool:
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT 1")
            return True
        except Exception:
            return False
```

**Dependencies**: `snowflake-connector-python` package
**Testing**: Integration tests with Snowflake trial account

---

#### Task 1.4: Update WarehouseConnection Model ⚪
**File**: `/posthog/warehouse/models/connection.py` (new file)

```python
from django.db import models
from posthog.models.utils import UUIDModel, sane_repr
from posthog.models.team import Team
from posthog.models.user import User
from encrypted_fields import EncryptedJSONField

class WarehouseConnection(UUIDModel):
    """Warehouse connection configuration"""

    PROVIDER_BIGQUERY = 'bigquery'
    PROVIDER_SNOWFLAKE = 'snowflake'
    PROVIDER_REDSHIFT = 'redshift'
    PROVIDER_DATABRICKS = 'databricks'

    PROVIDER_CHOICES = [
        (PROVIDER_BIGQUERY, 'BigQuery'),
        (PROVIDER_SNOWFLAKE, 'Snowflake'),
        (PROVIDER_REDSHIFT, 'Redshift'),
        (PROVIDER_DATABRICKS, 'Databricks'),
    ]

    MODE_SYNC = 'sync'
    MODE_DIRECT = 'direct'
    MODE_HYBRID = 'hybrid'

    MODE_CHOICES = [
        (MODE_SYNC, 'Sync to ClickHouse'),
        (MODE_DIRECT, 'Query directly'),
        (MODE_HYBRID, 'Hybrid (cached)'),
    ]

    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    provider = models.CharField(max_length=50, choices=PROVIDER_CHOICES)
    credentials = EncryptedJSONField()
    mode = models.CharField(max_length=20, choices=MODE_CHOICES, default=MODE_SYNC)
    is_active = models.BooleanField(default=True)
    config = models.JSONField(default=dict)  # timeout, cache_ttl, etc.
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_tested_at = models.DateTimeField(null=True, blank=True)
    last_test_status = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['team', 'name'],
                name='unique_connection_name_per_team'
            )
        ]

    __repr__ = sane_repr("name", "provider", "mode")

    def get_connector(self):
        """Return appropriate connector instance"""
        from posthog.warehouse.connectors import get_connector
        return get_connector(self)

    def test_connection(self) -> bool:
        """Test connection and update status"""
        try:
            connector = self.get_connector()
            success = connector.test_connection()
            self.last_test_status = success
            self.last_tested_at = timezone.now()
            self.save()
            return success
        except Exception as e:
            self.last_test_status = False
            self.last_tested_at = timezone.now()
            self.save()
            raise
```

**Migration**: Create migration for this model
**Dependencies**: django-encrypted-fields or similar
**Testing**: Model tests for validation, uniqueness constraints

---

#### Task 1.5: Create Connector Registry ⚪
**File**: `/posthog/warehouse/connectors/__init__.py`

```python
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from posthog.warehouse.models.connection import WarehouseConnection
    from .base import BaseWarehouseConnector

CONNECTORS = {
    'bigquery': 'posthog.warehouse.connectors.bigquery.BigQueryConnector',
    'snowflake': 'posthog.warehouse.connectors.snowflake.SnowflakeConnector',
    'redshift': 'posthog.warehouse.connectors.redshift.RedshiftConnector',
    'databricks': 'posthog.warehouse.connectors.databricks.DatabricksConnector',
}

def get_connector(connection: 'WarehouseConnection') -> 'BaseWarehouseConnector':
    """Factory function to get appropriate connector"""
    connector_path = CONNECTORS.get(connection.provider)
    if not connector_path:
        raise ValueError(f"Unknown warehouse provider: {connection.provider}")

    module_path, class_name = connector_path.rsplit('.', 1)
    module = __import__(module_path, fromlist=[class_name])
    connector_class = getattr(module, class_name)

    return connector_class(connection)
```

**Dependencies**: All connector implementations
**Testing**: Test connector factory with mocked connections

---

### Backend - Query Planner (P0)

#### Task 2.1: Create Query Planner ⚪
**File**: `/posthog/hogql/warehouse/query_planner.py`

```python
from typing import List, Optional, Union
from dataclasses import dataclass
from posthog.hogql.ast import SelectQuery, JoinExpr
from posthog.hogql.context import HogQLContext
from posthog.warehouse.models import WarehouseConnection

@dataclass
class DataSource:
    type: str  # 'posthog', 'warehouse'
    tables: List[str]
    connection_id: Optional[int] = None

@dataclass
class ExecutionPlan:
    strategy: str  # 'single_source', 'federated', 'cached'
    sources: List[DataSource]
    estimated_cost_usd: float
    cache_key: Optional[str] = None

class WarehouseQueryPlanner:
    """Analyze HogQL query and generate execution plan"""

    def __init__(self, context: HogQLContext):
        self.context = context
        self.team = context.team

    def plan(self, query: SelectQuery) -> ExecutionPlan:
        """Generate execution plan for query"""
        # 1. Extract all table references from query
        tables = self._extract_tables(query)

        # 2. Classify tables (PostHog vs warehouse)
        posthog_tables = []
        warehouse_tables = []
        for table in tables:
            if self._is_warehouse_table(table):
                warehouse_tables.append(table)
            else:
                posthog_tables.append(table)

        # 3. Determine execution strategy
        if not warehouse_tables:
            # Pure PostHog query
            return ExecutionPlan(
                strategy='single_source',
                sources=[DataSource(type='posthog', tables=posthog_tables)],
                estimated_cost_usd=0.0,
            )
        elif not posthog_tables:
            # Pure warehouse query
            connection = self._get_connection_for_table(warehouse_tables[0])
            return ExecutionPlan(
                strategy='single_source',
                sources=[DataSource(
                    type='warehouse',
                    tables=warehouse_tables,
                    connection_id=connection.id
                )],
                estimated_cost_usd=self._estimate_warehouse_cost(query, connection),
            )
        else:
            # Cross-source query - requires federation
            return ExecutionPlan(
                strategy='federated',
                sources=[
                    DataSource(type='posthog', tables=posthog_tables),
                    DataSource(
                        type='warehouse',
                        tables=warehouse_tables,
                        connection_id=self._get_connection_for_table(warehouse_tables[0]).id
                    ),
                ],
                estimated_cost_usd=self._estimate_warehouse_cost(query, connection),
            )

    def _extract_tables(self, query: SelectQuery) -> List[str]:
        """Extract all table names from query AST"""
        # Walk AST and collect table references
        # Implementation depends on HogQL AST structure
        pass

    def _is_warehouse_table(self, table_name: str) -> bool:
        """Check if table is from warehouse"""
        # Check if table exists in DataWarehouseTable with direct mode
        from posthog.warehouse.models import DataWarehouseTable
        return DataWarehouseTable.objects.filter(
            team=self.team,
            name=table_name,
            external_data_source__connection__mode='direct'
        ).exists()

    def _get_connection_for_table(self, table_name: str) -> WarehouseConnection:
        """Get warehouse connection for table"""
        from posthog.warehouse.models import DataWarehouseTable
        table = DataWarehouseTable.objects.get(team=self.team, name=table_name)
        return table.external_data_source.connection

    def _estimate_warehouse_cost(self, query: SelectQuery, connection: WarehouseConnection) -> float:
        """Estimate cost of warehouse query"""
        # Convert HogQL to warehouse SQL and estimate
        connector = connection.get_connector()
        # Simplified - would need SQL generation
        return 0.0
```

**Dependencies**: HogQL AST, warehouse models
**Testing**: Unit tests with various query patterns
**Files to Reference**:
- `/posthog/hogql/database/database.py` for table registry pattern
- `/posthog/hogql/query.py` for query execution flow

---

#### Task 2.2: Create Query Executor ⚪
**File**: `/posthog/hogql/warehouse/query_executor.py`

```python
from typing import Any, Dict, List
from posthog.hogql.ast import SelectQuery
from posthog.hogql.context import HogQLContext
from .query_planner import WarehouseQueryPlanner, ExecutionPlan

class WarehouseQueryExecutor:
    """Execute queries across PostHog and warehouse sources"""

    def __init__(self, context: HogQLContext):
        self.context = context
        self.planner = WarehouseQueryPlanner(context)

    def execute(self, query: SelectQuery) -> Dict[str, Any]:
        """Execute query using optimal execution plan"""
        plan = self.planner.plan(query)

        if plan.strategy == 'single_source':
            return self._execute_single_source(query, plan)
        elif plan.strategy == 'federated':
            return self._execute_federated(query, plan)
        elif plan.strategy == 'cached':
            return self._execute_cached(query, plan)
        else:
            raise ValueError(f"Unknown strategy: {plan.strategy}")

    def _execute_single_source(self, query: SelectQuery, plan: ExecutionPlan) -> Dict[str, Any]:
        """Execute query against single source"""
        source = plan.sources[0]

        if source.type == 'posthog':
            # Use existing ClickHouse execution
            from posthog.hogql.query import execute_hogql_query
            return execute_hogql_query(query, self.context.team)
        else:
            # Execute on warehouse
            return self._execute_on_warehouse(query, source.connection_id)

    def _execute_on_warehouse(self, query: SelectQuery, connection_id: int) -> Dict[str, Any]:
        """Execute query on warehouse"""
        from posthog.warehouse.models import WarehouseConnection

        connection = WarehouseConnection.objects.get(id=connection_id)
        connector = connection.get_connector()

        # Convert HogQL to warehouse SQL
        sql = self._hogql_to_warehouse_sql(query, connection.provider)

        # Execute query
        result = connector.execute_query(sql)

        return {
            'results': result.rows,
            'columns': result.columns,
            'types': [],  # Would need to map warehouse types
            'metadata': {
                'execution_time_ms': result.execution_time_ms,
                'bytes_processed': result.bytes_processed,
                'cached': result.cached,
                'source': 'warehouse',
                'connection': connection.name,
            }
        }

    def _execute_federated(self, query: SelectQuery, plan: ExecutionPlan) -> Dict[str, Any]:
        """Execute cross-source query"""
        # Phase 1: Execute warehouse subquery
        warehouse_source = next(s for s in plan.sources if s.type == 'warehouse')
        warehouse_results = self._execute_on_warehouse(query, warehouse_source.connection_id)

        # Phase 2: Create temp table in ClickHouse with warehouse results
        # Phase 3: Execute PostHog query with join to temp table
        # Phase 4: Clean up temp table

        # Simplified implementation - full version would need:
        # - Query splitting (separate warehouse and PostHog parts)
        # - Temp table creation
        # - Result joining
        raise NotImplementedError("Federated queries not yet implemented")

    def _hogql_to_warehouse_sql(self, query: SelectQuery, provider: str) -> str:
        """Convert HogQL AST to warehouse-specific SQL"""
        # This is complex - would need separate compiler per warehouse
        # For MVP, could start with passthrough for simple queries
        from posthog.hogql.printer import print_ast
        return print_ast(query)  # Simplified
```

**Dependencies**: Query planner, connectors, HogQL printer
**Testing**: Integration tests with real warehouse queries
**Note**: Federated queries are complex - can be deferred to Phase 2

---

### Backend - API Endpoints (P0)

#### Task 3.1: Warehouse Connection API ⚪
**File**: `/posthog/warehouse/api/connection.py` (new file)

```python
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.warehouse.models import WarehouseConnection
from posthog.warehouse.api.serializers import WarehouseConnectionSerializer

class WarehouseConnectionViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    queryset = WarehouseConnection.objects.all()
    serializer_class = WarehouseConnectionSerializer

    def get_queryset(self):
        return super().get_queryset().filter(team=self.team)

    @action(detail=False, methods=['post'])
    def test(self, request):
        """Test connection before saving"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Create temporary connection (don't save)
        connection = WarehouseConnection(**serializer.validated_data)
        connection.team = self.team

        try:
            success = connection.test_connection()
            if success:
                return Response({'status': 'success', 'message': 'Connection successful'})
            else:
                return Response(
                    {'status': 'error', 'message': 'Connection failed'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        except Exception as e:
            return Response(
                {'status': 'error', 'message': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )

    @action(detail=True, methods=['get'])
    def schema(self, request, pk=None):
        """Get schema for connection"""
        connection = self.get_object()
        connector = connection.get_connector()
        schema = connector.get_schema()

        return Response({
            'tables': [
                {
                    'name': table.name,
                    'columns': [
                        {'name': col.name, 'type': col.type, 'nullable': col.nullable}
                        for col in table.columns
                    ],
                    'row_count': table.row_count,
                    'size_bytes': table.size_bytes,
                }
                for table in schema
            ]
        })

    @action(detail=True, methods=['post'])
    def estimate_cost(self, request, pk=None):
        """Estimate cost for query"""
        connection = self.get_object()
        sql = request.data.get('sql')

        if not sql:
            return Response(
                {'error': 'SQL query required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        connector = connection.get_connector()
        cost = connector.estimate_cost(sql)

        return Response({
            'estimated_bytes': cost.estimated_bytes,
            'estimated_cost_usd': cost.estimated_cost_usd,
            'warning_message': cost.warning_message,
        })
```

**Dependencies**: WarehouseConnection model, connectors
**Testing**: API tests for CRUD operations, test endpoint, schema endpoint
**Files to Reference**: `/posthog/warehouse/api/external_data_source.py`

---

#### Task 3.2: Update Query API for Warehouse Execution ⚪
**File**: `/posthog/api/query.py` (modify existing)

```python
# Add to existing QueryViewSet

from posthog.hogql.warehouse.query_executor import WarehouseQueryExecutor

class QueryViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    # ... existing code ...

    def create(self, request, *args, **kwargs) -> Response:
        # ... existing validation ...

        # Check if query involves warehouse tables
        if self._query_uses_warehouse(query_dict):
            # Use warehouse executor
            from posthog.hogql.warehouse.query_executor import WarehouseQueryExecutor
            from posthog.hogql.context import HogQLContext

            context = HogQLContext(team=self.team, ...)
            executor = WarehouseQueryExecutor(context)

            # Get execution plan for cost estimation
            plan = executor.planner.plan(query)

            # Warn if expensive
            if plan.estimated_cost_usd > 1.0:
                # Could require confirmation or block if over limit
                pass

            result = executor.execute(query)
            return Response(result)

        # ... existing PostHog-only execution ...
```

**Dependencies**: Query executor, query planner
**Testing**: API tests with warehouse queries
**Note**: Preserve existing behavior for non-warehouse queries

---

### Frontend - Connection Management (P0)

#### Task 4.1: Connection Settings Page ⚪
**File**: `/frontend/src/scenes/data-warehouse/settings/Connections.tsx` (new)

```tsx
import { LemonButton, LemonInput, LemonSelect } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { connectionsLogic } from './connectionsLogic'

export function Connections(): JSX.Element {
    const { connections, connectionsLoading } = useValues(connectionsLogic)
    const { deleteConnection, testConnection } = useActions(connectionsLogic)

    return (
        <div>
            <h1>Warehouse connections</h1>
            <p>Connect your data warehouse to query alongside PostHog data</p>

            <LemonButton type="primary" to="/data-warehouse/connections/new">
                Add connection
            </LemonButton>

            <div className="mt-4">
                {connections.map((connection) => (
                    <ConnectionCard
                        key={connection.id}
                        connection={connection}
                        onTest={() => testConnection(connection.id)}
                        onDelete={() => deleteConnection(connection.id)}
                    />
                ))}
            </div>
        </div>
    )
}

function ConnectionCard({ connection, onTest, onDelete }): JSX.Element {
    return (
        <div className="border rounded p-4 mb-2">
            <div className="flex justify-between">
                <div>
                    <h3>{connection.name}</h3>
                    <div className="text-muted">
                        {connection.provider} • {connection.mode}
                    </div>
                    {connection.last_tested_at && (
                        <div className="text-xs">
                            Last tested: {connection.last_tested_at}
                            {connection.last_test_status ? ' ✓' : ' ✗'}
                        </div>
                    )}
                </div>
                <div className="flex gap-2">
                    <LemonButton onClick={onTest}>Test</LemonButton>
                    <LemonButton to={`/data-warehouse/connections/${connection.id}`}>
                        Edit
                    </LemonButton>
                    <LemonButton status="danger" onClick={onDelete}>
                        Delete
                    </LemonButton>
                </div>
            </div>
        </div>
    )
}
```

**Dependencies**: Lemon UI components, connections logic
**Testing**: Storybook stories, jest tests

---

#### Task 4.2: Connection Form (Add/Edit) ⚪
**File**: `/frontend/src/scenes/data-warehouse/settings/ConnectionForm.tsx` (new)

```tsx
import { LemonButton, LemonInput, LemonSelect, LemonFileInput } from '@posthog/lemon-ui'
import { Form } from 'kea-forms'
import { connectionFormLogic } from './connectionFormLogic'

export function ConnectionForm(): JSX.Element {
    const { connection, isConnectionValid, providers } = useValues(connectionFormLogic)
    const { setConnectionValue, submitConnection, testConnection } = useActions(connectionFormLogic)

    return (
        <Form logic={connectionFormLogic} formKey="connection">
            <h2>{connection.id ? 'Edit' : 'Add'} connection</h2>

            <div className="space-y-4">
                <LemonInput
                    label="Connection name"
                    value={connection.name}
                    onChange={(name) => setConnectionValue('name', name)}
                />

                <LemonSelect
                    label="Provider"
                    value={connection.provider}
                    onChange={(provider) => setConnectionValue('provider', provider)}
                    options={providers}
                />

                {connection.provider === 'bigquery' && (
                    <BigQueryCredentials
                        credentials={connection.credentials}
                        onChange={(creds) => setConnectionValue('credentials', creds)}
                    />
                )}

                {connection.provider === 'snowflake' && (
                    <SnowflakeCredentials
                        credentials={connection.credentials}
                        onChange={(creds) => setConnectionValue('credentials', creds)}
                    />
                )}

                <LemonSelect
                    label="Query mode"
                    value={connection.mode}
                    onChange={(mode) => setConnectionValue('mode', mode)}
                    options={[
                        { value: 'sync', label: 'Sync to PostHog (recommended)' },
                        { value: 'direct', label: 'Query directly (real-time)' },
                        { value: 'hybrid', label: 'Hybrid (cached queries)' },
                    ]}
                />

                <div className="flex gap-2">
                    <LemonButton type="secondary" onClick={testConnection}>
                        Test connection
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={submitConnection}
                        disabled={!isConnectionValid}
                    >
                        Save
                    </LemonButton>
                </div>
            </div>
        </Form>
    )
}

function BigQueryCredentials({ credentials, onChange }): JSX.Element {
    return (
        <div>
            <LemonFileInput
                label="Service account JSON"
                accept=".json"
                onChange={(file) => {
                    const reader = new FileReader()
                    reader.onload = (e) => {
                        const json = JSON.parse(e.target.result)
                        onChange({ service_account_json: json })
                    }
                    reader.readAsText(file)
                }}
            />
            <LemonInput
                label="Project ID"
                value={credentials.project_id}
                onChange={(project_id) => onChange({ ...credentials, project_id })}
            />
            <LemonInput
                label="Default dataset (optional)"
                value={credentials.default_dataset}
                onChange={(default_dataset) => onChange({ ...credentials, default_dataset })}
            />
        </div>
    )
}
```

**Dependencies**: Lemon UI, kea-forms, connection form logic
**Testing**: Jest tests for form validation, Storybook stories

---

#### Task 4.3: Enhanced SQL Editor with Warehouse Support ⚪
**File**: `/frontend/src/scenes/data-warehouse/editor/QueryWindow.tsx` (modify existing)

```tsx
// Add warehouse table indicators and cost estimation

export function QueryWindow({ query }: QueryWindowProps): JSX.Element {
    const { estimatedCost, usesWarehouse } = useValues(queryLogic)

    return (
        <div className="query-window">
            {/* Existing Monaco editor */}
            <MonacoEditor ... />

            {/* Cost warning */}
            {usesWarehouse && estimatedCost && estimatedCost.estimated_cost_usd > 0.1 && (
                <LemonBanner type="warning">
                    This query will scan {estimatedCost.estimated_bytes / 1e9}GB from your warehouse
                    (estimated cost: ${estimatedCost.estimated_cost_usd.toFixed(2)})
                </LemonBanner>
            )}

            {/* Execute button */}
            <LemonButton onClick={executeQuery}>
                Run query
            </LemonButton>
        </div>
    )
}
```

**Dependencies**: Monaco editor, query logic
**Testing**: Jest tests for cost warning display

---

#### Task 4.4: Warehouse Table Browser ⚪
**File**: `/frontend/src/scenes/data-warehouse/settings/TableBrowser.tsx` (new)

```tsx
import { LemonTable } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { tableBrowserLogic } from './tableBrowserLogic'

export function TableBrowser({ connectionId }: { connectionId: number }): JSX.Element {
    const { tables, tablesLoading } = useValues(tableBrowserLogic({ connectionId }))

    return (
        <div>
            <h3>Available tables</h3>
            <LemonTable
                dataSource={tables}
                columns={[
                    {
                        title: 'Table',
                        dataIndex: 'name',
                        render: (name) => <code>{name}</code>,
                    },
                    {
                        title: 'Rows',
                        dataIndex: 'row_count',
                        render: (count) => count?.toLocaleString() ?? 'Unknown',
                    },
                    {
                        title: 'Size',
                        dataIndex: 'size_bytes',
                        render: (bytes) => bytes ? formatBytes(bytes) : 'Unknown',
                    },
                    {
                        title: 'Actions',
                        render: (_, table) => (
                            <LemonButton to={`/data-warehouse/editor?table=${table.name}`}>
                                Query
                            </LemonButton>
                        ),
                    },
                ]}
                loading={tablesLoading}
            />
        </div>
    )
}
```

**Dependencies**: LemonTable, table browser logic
**Testing**: Jest tests, Storybook stories

---

### Backend - Database Registry Integration (P0)

#### Task 5.1: Register Warehouse Tables in HogQL Database ⚪
**File**: `/posthog/hogql/database/database.py` (modify existing)

```python
# Add warehouse tables to database registry

class Database:
    def __init__(self, team: Team, ...):
        # ... existing initialization ...

        # Add warehouse tables
        self._add_warehouse_tables()

    def _add_warehouse_tables(self):
        """Add warehouse tables to database registry"""
        from posthog.warehouse.models import DataWarehouseTable

        warehouse_tables = DataWarehouseTable.objects.filter(
            team=self.team,
            external_data_source__connection__is_active=True,
        ).select_related('external_data_source__connection')

        for table in warehouse_tables:
            connection = table.external_data_source.connection

            if connection.mode == 'direct':
                # Direct query mode - create virtual table
                self.tables[table.name] = WarehouseTable(
                    name=table.name,
                    connection=connection,
                    schema=table.get_schema(),
                )
            else:
                # Sync mode - already in ClickHouse
                # Use existing DataWarehouseTable logic
                pass
```

**Dependencies**: DataWarehouseTable model, connectors
**Testing**: Unit tests for database registry with warehouse tables
**Files to Reference**: `/posthog/hogql/database/database.py:150-880`

---

#### Task 5.2: Create WarehouseTable Class ⚪
**File**: `/posthog/hogql/database/warehouse.py` (new)

```python
from posthog.hogql.database.models import Table, StringDatabaseField
from posthog.warehouse.models import WarehouseConnection

class WarehouseTable(Table):
    """Virtual table backed by warehouse connection"""

    def __init__(self, name: str, connection: WarehouseConnection, schema: dict):
        self.connection = connection
        self._schema = schema

        # Convert warehouse schema to HogQL fields
        fields = {}
        for column in schema['columns']:
            fields[column['name']] = self._convert_type(column['type'])

        super().__init__(
            name=name,
            fields=fields,
        )

    def _convert_type(self, warehouse_type: str):
        """Convert warehouse type to HogQL field type"""
        # Map warehouse types to HogQL types
        type_map = {
            'STRING': StringDatabaseField,
            'INTEGER': IntegerDatabaseField,
            'FLOAT': FloatDatabaseField,
            'TIMESTAMP': DateTimeDatabaseField,
            # ... more mappings
        }
        return type_map.get(warehouse_type.upper(), StringDatabaseField)(name='')

    def to_printed_clickhouse(self, context):
        """This table doesn't exist in ClickHouse - handled by executor"""
        raise NotImplementedError("Warehouse tables must be handled by WarehouseQueryExecutor")
```

**Dependencies**: HogQL database models
**Testing**: Unit tests for type conversion, table creation

---

### Testing & Documentation (P0)

#### Task 6.1: Integration Tests ⚪
**File**: `/posthog/warehouse/test/test_connectors.py` (new)

```python
import pytest
from posthog.warehouse.connectors.bigquery import BigQueryConnector
from posthog.warehouse.models import WarehouseConnection

@pytest.mark.integration
class TestBigQueryConnector:
    def test_execute_query(self, bigquery_connection):
        connector = BigQueryConnector(bigquery_connection)
        result = connector.execute_query("SELECT 1 as test")

        assert len(result.rows) == 1
        assert result.rows[0]['test'] == 1
        assert 'test' in result.columns

    def test_get_schema(self, bigquery_connection):
        connector = BigQueryConnector(bigquery_connection)
        schema = connector.get_schema('my_dataset')

        assert len(schema) > 0
        assert all(hasattr(table, 'name') for table in schema)

    def test_estimate_cost(self, bigquery_connection):
        connector = BigQueryConnector(bigquery_connection)
        cost = connector.estimate_cost("SELECT * FROM large_table")

        assert cost.estimated_bytes > 0
        assert cost.estimated_cost_usd >= 0

@pytest.fixture
def bigquery_connection():
    return WarehouseConnection(
        provider='bigquery',
        credentials={
            'service_account_json': {...},
            'project_id': 'test-project',
        },
        config={'timeout_seconds': 30},
    )
```

**Dependencies**: Test fixtures, warehouse connections
**Testing**: Run against test BigQuery/Snowflake instances

---

#### Task 6.2: API Tests ⚪
**File**: `/posthog/warehouse/test/test_connection_api.py` (new)

```python
from rest_framework.test import APITestCase
from posthog.warehouse.models import WarehouseConnection

class TestWarehouseConnectionAPI(APITestCase):
    def test_create_connection(self):
        response = self.client.post('/api/warehouse/connections/', {
            'name': 'My BigQuery',
            'provider': 'bigquery',
            'credentials': {...},
            'mode': 'direct',
        })

        assert response.status_code == 201
        assert WarehouseConnection.objects.filter(name='My BigQuery').exists()

    def test_test_connection(self):
        response = self.client.post('/api/warehouse/connections/test/', {
            'provider': 'bigquery',
            'credentials': {...},
        })

        assert response.status_code == 200
        assert response.json()['status'] == 'success'

    def test_get_schema(self):
        connection = WarehouseConnection.objects.create(...)
        response = self.client.get(f'/api/warehouse/connections/{connection.id}/schema/')

        assert response.status_code == 200
        assert 'tables' in response.json()
```

**Dependencies**: API client, test fixtures
**Testing**: Run as part of CI/CD

---

#### Task 6.3: Documentation ⚪
**File**: `/docs/data-warehouse/connections.md` (new)

Create comprehensive docs covering:
- Setup guide per warehouse (BigQuery, Snowflake, etc.)
- Authentication and credentials
- Query modes (sync vs. direct vs. hybrid)
- SQL editor usage
- Dashboard integration
- Troubleshooting common issues
- Performance optimization tips
- Security best practices

**Dependencies**: None
**Testing**: Review by docs team

---

## Phase 2: Enhanced Integration

### Backend - Insight Builder Support (P1)

#### Task 7.1: Warehouse Data Source for Insights ⚪
**File**: `/posthog/models/insight.py` (modify)

Allow insights to use warehouse tables as data source:
- Update InsightSerializer to accept warehouse table references
- Support basic aggregations (COUNT, SUM, AVG) on warehouse tables
- Generate HogQL from insight filters for warehouse tables

**Dependencies**: Insights framework, HogQL query generation
**Files to Reference**: `/posthog/models/insight.py`

---

#### Task 7.2: Cross-Source Filters ⚪
**File**: `/posthog/hogql/filters.py` (new)

Support dashboard filters that apply to both PostHog and warehouse data:
- Date range filters → apply to warehouse timestamp columns
- Property filters → apply to warehouse columns when available
- Cohort filters → sync cohort to warehouse or use subquery

**Dependencies**: Filter system, query planner

---

### Backend - Materialized Views (P1)

#### Task 8.1: Scheduled Warehouse Query Refresh ⚪
**File**: `/posthog/warehouse/tasks/refresh.py` (new)

```python
from celery import shared_task
from posthog.warehouse.models import MaterializedWarehouseQuery

@shared_task
def refresh_materialized_query(query_id: int):
    """Refresh materialized warehouse query"""
    query = MaterializedWarehouseQuery.objects.get(id=query_id)

    # Execute warehouse query
    connector = query.connection.get_connector()
    result = connector.execute_query(query.sql)

    # Store in ClickHouse
    from posthog.client import sync_execute
    sync_execute(f"""
        INSERT INTO materialized_warehouse_queries
        SELECT * FROM input(...)
    """, result.rows)

    # Update last refreshed timestamp
    query.last_refreshed_at = timezone.now()
    query.save()
```

**Dependencies**: Celery, connectors, ClickHouse client

---

#### Task 8.2: Incremental Refresh Logic ⚪
**File**: `/posthog/warehouse/tasks/incremental.py` (new)

Support incremental updates:
- Track high water mark (e.g., max timestamp)
- Only fetch new/updated rows
- Handle deletes (soft delete or full refresh)
- Conflict resolution

**Dependencies**: Materialized query model, connectors

---

### Backend - Write-Back (Reverse ETL) (P1)

#### Task 9.1: Cohort Export to Warehouse ⚪
**File**: `/posthog/warehouse/export/cohort.py` (new)

```python
from posthog.models import Cohort
from posthog.warehouse.models import WarehouseConnection

def export_cohort_to_warehouse(cohort: Cohort, connection: WarehouseConnection, table_name: str):
    """Export cohort members to warehouse table"""
    # Get cohort members
    from posthog.models import Person
    members = Person.objects.filter(cohort=cohort)

    # Prepare data
    rows = [{'person_id': p.id, 'distinct_id': p.distinct_ids[0]} for p in members]

    # Write to warehouse
    connector = connection.get_connector()
    connector.write_table(table_name, rows)
```

**Dependencies**: Cohort model, connectors with write capability
**Note**: Requires write-enabled warehouse credentials (security consideration)

---

### Frontend - No-Code Query Builder (P1)

#### Task 10.1: Warehouse Data Source in Insight Builder ⚪
**File**: `/frontend/src/scenes/insights/InsightBuilder.tsx` (modify)

Add warehouse tables as data source option:
- Data source selector: "PostHog events", "PostHog persons", "Warehouse table"
- Table selector (fetch from connection schema)
- Column selector (show available columns)
- Filter builder (WHERE clauses)
- Aggregation builder (GROUP BY, aggregations)

**Dependencies**: Insight builder, warehouse API

---

#### Task 10.2: Cross-Source Insight Configuration ⚪
**File**: `/frontend/src/scenes/insights/CrossSourceInsight.tsx` (new)

UI for joining PostHog and warehouse data:
- Select PostHog data source (events/persons)
- Select warehouse table
- Define join key (e.g., person.email = warehouse.customer_email)
- Configure filters on both sides
- Preview join results

**Dependencies**: Insight builder, join logic

---

### Infrastructure - Caching (P1)

#### Task 11.1: Warehouse Query Result Cache ⚪
**File**: `/posthog/warehouse/cache.py` (new)

Implement intelligent caching:
- Redis cache for small results (< 1MB)
- ClickHouse cache table for large results
- Configurable TTL per connection
- Cache key includes query + connection + parameters
- Cache invalidation on demand or TTL expiry

**Dependencies**: Redis, ClickHouse

---

#### Task 11.2: Cache Warming for Dashboards ⚪
**File**: `/posthog/warehouse/tasks/cache_warming.py` (new)

Pre-execute dashboard queries:
- Identify dashboards with warehouse queries
- Schedule cache warming before peak usage times
- Monitor cache hit rates
- Alert on cache misses for critical dashboards

**Dependencies**: Caching layer, Celery

---

## Phase 3: Enterprise Features

### Security & Governance (P2)

#### Task 12.1: Column-Level Access Control ⚪
**File**: `/posthog/warehouse/rbac.py` (new)

```python
class WarehouseAccessControl:
    """Column-level access control for warehouse tables"""

    def filter_columns(self, table: str, columns: List[str], user: User) -> List[str]:
        """Filter columns based on user permissions"""
        # Check user role and team permissions
        # Return only allowed columns
        pass

    def mask_sensitive_data(self, results: List[Dict], table: str, user: User) -> List[Dict]:
        """Mask sensitive columns in query results"""
        # Identify PII columns (email, phone, SSN, etc.)
        # Mask or redact based on user permissions
        pass
```

**Dependencies**: User model, permissions system

---

#### Task 12.2: Query Approval Workflow ⚪
**File**: `/posthog/warehouse/approvals.py` (new)

Require approval for expensive queries:
- Define cost thresholds requiring approval
- Workflow: Submit → Approve → Execute
- Notification system for approvers
- Audit log of approvals/rejections

**Dependencies**: Notifications, audit logging

---

### Cost Management (P2)

#### Task 13.1: Budget Limits and Alerts ⚪
**File**: `/posthog/warehouse/budgets.py` (new)

```python
class WarehouseBudgetManager:
    """Manage warehouse query budgets"""

    def check_budget(self, team: Team, estimated_cost: float) -> bool:
        """Check if query is within budget"""
        current_spend = self.get_monthly_spend(team)
        budget_limit = team.warehouse_budget_usd
        return (current_spend + estimated_cost) <= budget_limit

    def record_spend(self, team: Team, actual_cost: float, query: str):
        """Record query cost for billing/reporting"""
        WarehouseQueryCost.objects.create(
            team=team,
            cost_usd=actual_cost,
            query=query,
            executed_at=timezone.now(),
        )
```

**Dependencies**: Cost tracking model, query executor

---

#### Task 13.2: Cost Dashboard ⚪
**File**: `/frontend/src/scenes/data-warehouse/costs/CostDashboard.tsx` (new)

Show warehouse query costs:
- Cost over time (daily/weekly/monthly)
- Cost by connection
- Cost by user
- Cost by dashboard/insight
- Top expensive queries
- Budget utilization

**Dependencies**: Cost API, charting library

---

### Multi-Warehouse Federation (P2)

#### Task 14.1: Cross-Warehouse Query Support ⚪
**File**: `/posthog/hogql/warehouse/federation.py` (new)

Enable queries across multiple warehouses:
- Identify tables from different connections
- Execute subqueries in each warehouse
- Join results in ClickHouse or dominant warehouse
- Optimize by moving small table to large table's warehouse

**Dependencies**: Query planner, connectors

---

#### Task 14.2: Warehouse Load Balancing ⚪
**File**: `/posthog/warehouse/load_balancing.py` (new)

Distribute queries across warehouse replicas:
- Health check for warehouse endpoints
- Route queries to healthy replicas
- Failover to backup warehouse
- Circuit breaker for failed warehouses

**Dependencies**: Connectors, health monitoring

---

## Infrastructure & DevOps

### Task 15: Package Dependencies ⚪
**File**: `requirements.txt` or `pyproject.toml`

Add warehouse connector libraries:
```
google-cloud-bigquery>=3.0.0
snowflake-connector-python>=3.0.0
psycopg2-binary>=2.9.0  # for Redshift
databricks-sql-connector>=2.0.0
```

**Testing**: Ensure no dependency conflicts

---

### Task 16: Environment Configuration ⚪
**File**: `posthog/settings.py`

Add warehouse settings:
```python
# Warehouse configuration
WAREHOUSE_CREDENTIALS_ENCRYPTION_KEY = env('WAREHOUSE_CREDENTIALS_ENCRYPTION_KEY')
WAREHOUSE_QUERY_TIMEOUT_SECONDS = env.int('WAREHOUSE_QUERY_TIMEOUT_SECONDS', 300)
WAREHOUSE_CACHE_TTL_SECONDS = env.int('WAREHOUSE_CACHE_TTL_SECONDS', 3600)
WAREHOUSE_MAX_RESULT_SIZE_BYTES = env.int('WAREHOUSE_MAX_RESULT_SIZE_BYTES', 100_000_000)
WAREHOUSE_ENABLE_COST_ESTIMATION = env.bool('WAREHOUSE_ENABLE_COST_ESTIMATION', True)
```

**Testing**: Validate settings loading

---

### Task 17: Database Migrations ⚪
**Files**: `/posthog/warehouse/migrations/`

Create migrations for:
1. `WarehouseConnection` model
2. `WarehouseQueryLog` model (audit logging)
3. `WarehouseQueryCost` model (cost tracking)
4. `MaterializedWarehouseQuery` model (materialized views)

**Testing**: Test migrations on dev database

---

### Task 18: Monitoring & Alerting ⚪
**File**: `/posthog/warehouse/monitoring.py` (new)

Add monitoring for:
- Warehouse query execution time (P50, P95, P99)
- Warehouse query failure rate
- Cache hit rate
- Cost tracking and alerts
- Connection health status

**Dependencies**: Prometheus, Grafana, or existing monitoring stack

---

## Documentation & Training

### Task 19: User Documentation ⚪
**Files**: `/docs/data-warehouse/`

Create docs for:
1. **Setup Guides**:
   - BigQuery connection setup
   - Snowflake connection setup
   - Redshift connection setup
   - Databricks connection setup
2. **User Guides**:
   - Querying warehouse data with SQL editor
   - Creating insights from warehouse tables
   - Dashboard integration
   - Query modes (sync/direct/hybrid)
3. **Advanced Topics**:
   - Performance optimization
   - Cost management
   - Security best practices
   - Troubleshooting

---

### Task 20: API Documentation ⚪
**File**: `/docs/api/warehouse.md`

Document API endpoints:
- `POST /api/warehouse/connections/` - Create connection
- `GET /api/warehouse/connections/` - List connections
- `POST /api/warehouse/connections/test/` - Test connection
- `GET /api/warehouse/connections/:id/schema/` - Get schema
- `POST /api/warehouse/connections/:id/estimate_cost/` - Estimate cost
- `POST /api/query/` - Execute query (with warehouse support)

---

### Task 21: Migration Guide ⚪
**File**: `/docs/data-warehouse/migration-from-sync.md`

Guide for customers migrating from sync mode to direct mode:
- Comparison of modes
- When to use each mode
- Migration steps
- Performance considerations
- Troubleshooting

---

## Testing Strategy

### Unit Tests
- Connector implementations (mock warehouse APIs)
- Query planner logic
- Cost estimation
- Query optimizer
- Database registry

### Integration Tests
- End-to-end query execution against test warehouses
- API endpoints with real connectors
- Cache behavior
- Error handling

### Performance Tests
- Query execution time benchmarks
- Cache hit rate optimization
- Concurrent query handling
- Large result set handling

### Security Tests
- Credential encryption/decryption
- Team isolation
- SQL injection prevention
- Access control enforcement

---

## Rollout Plan

### Phase 1: Private Beta (Weeks 1-4)
- [ ] Complete MVP tasks (P0)
- [ ] Deploy to staging
- [ ] Invite 10 beta customers
- [ ] Gather feedback
- [ ] Fix critical bugs

### Phase 2: Public Beta (Weeks 5-8)
- [ ] Complete Phase 2 tasks (P1)
- [ ] Announce public beta
- [ ] Update docs and marketing materials
- [ ] Monitor usage and performance
- [ ] Iterate based on feedback

### Phase 3: General Availability (Weeks 9-12)
- [ ] Complete enterprise features (P2)
- [ ] Performance optimization
- [ ] Launch announcement
- [ ] Customer success training
- [ ] Monitor adoption metrics

---

## Success Metrics

### Adoption Metrics
- Number of teams with warehouse connections: Target 50 by Q1
- Number of warehouse queries per week: Target 10,000 by Q2
- % of dashboards with warehouse data: Target 20% by Q2

### Performance Metrics
- P95 query latency: < 5 seconds for direct queries
- Cache hit rate: > 60% for dashboard queries
- Query failure rate: < 1%

### Value Metrics
- Customer NPS for warehouse integration: > 8.0
- Time saved vs. building custom integration: 40 hours/customer
- Revenue from warehouse feature upsells: Track separately

---

## Known Risks & Mitigations

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| Warehouse query costs surprise customers | High | Medium | Clear cost estimation, warnings, budget limits |
| Poor query performance | High | Medium | Intelligent caching, optimization, query timeouts |
| Security breach via credentials | Critical | Low | Encryption at rest/transit, audit logging, read-only access |
| Cross-source joins too slow | Medium | High | Materialization, query optimization, clear UX expectations |
| Warehouse API rate limits | Medium | Medium | Exponential backoff, query queuing, user warnings |
| Complex HogQL→warehouse SQL translation | Medium | Medium | Start with passthrough SQL, incrementally add features |

---

## Open Questions

1. **Default Query Timeout**: 300s seems reasonable, but should it vary by warehouse?
2. **Cache TTL**: 1 hour default - too short? Too long?
3. **Federated Joins**: Should we limit join size to prevent OOM? What's the threshold?
4. **Write-Back Permissions**: Should cohort export require separate write credentials?
5. **Multi-Tenancy**: Should connections be org-level or team-level? (Currently team-level)
6. **Cost Attribution**: How to handle shared connections across teams?

---

## Next Steps

1. **Review and Prioritize**: Review this TODO with product/eng team
2. **Spike Work**: Prototype query planner and BigQuery connector
3. **Finalize Architecture**: Review technical design decisions
4. **Create Jira Tickets**: Break down tasks into trackable work items
5. **Assign Ownership**: Identify DRI for each component area
6. **Set Timeline**: Establish milestones and deadlines

---

**Document Version**: 1.0
**Last Updated**: 2025-10-28
**Owner**: Engineering Team
**Status**: Planning
