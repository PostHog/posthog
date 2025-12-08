# Pipeline Sources Analysis

This document provides a comprehensive analysis of all data import sources in the PostHog data warehouse, including their features, implementation patterns, and capabilities.

## Overview

Total sources: 33

## Database vs Non-Database Sources

### Database Sources (9)

1. **BigQuery** - Google Cloud data warehouse
2. **MongoDB** - NoSQL document database
3. **MSSQL** - Microsoft SQL Server / Azure SQL
4. **MySQL** - MySQL/MariaDB relational database
5. **Postgres** - PostgreSQL relational database
6. **Redshift** - Amazon Redshift data warehouse (stub)
7. **Snowflake** - Snowflake cloud data warehouse
8. **Supabase** - Supabase (extends PostgresSource)
9. **Temporalio** - Temporal workflow database

### Non-Database / API Sources (24)

1. **Ashby** - Recruiting platform (stub)
2. **Bing Ads** - Microsoft advertising platform
3. **Braze** - Customer engagement platform (stub)
4. **Chargebee** - Subscription billing platform
5. **Customer.io** - Marketing automation (stub)
6. **DoIt** - Cloud cost management
7. **GitHub** - Version control platform (stub)
8. **Google Ads** - Google advertising platform
9. **Google Sheets** - Google Sheets spreadsheet
10. **Hubspot** - CRM and marketing platform
11. **Klaviyo** - Email marketing (stub)
12. **LinkedIn Ads** - LinkedIn advertising platform
13. **Mailchimp** - Email marketing (stub)
14. **Mailjet** - Email service (stub)
15. **Meta Ads** - Facebook/Instagram advertising
16. **Polar** - Developer monetization (stub)
17. **Reddit Ads** - Reddit advertising platform
18. **RevenueCat** - In-app subscription (stub)
19. **Salesforce** - CRM platform
20. **Shopify** - E-commerce platform
21. **Stripe** - Payment processing platform
22. **TikTok Ads** - TikTok advertising platform
23. **Vitally** - Customer success platform
24. **Zendesk** - Customer support platform

## Feature Analysis

### 1. Row Count Retrieval from Schema API

**Implemented:**

- **Postgres** ✅ - `get_postgres_row_count()` function, used when `with_counts=True` in `get_schemas()`
  - Returns row counts for all tables/views in schema
  - Used to show table sizes in UI before sync

**Not Implemented:** All other sources

### 1a. Rows to Sync (Runtime Estimation)

Sources that calculate and return `rows_to_sync` in `SourceResponse` during actual sync:

**Implemented (6 sources):**

- **BigQuery** ✅ - `_get_rows_to_sync()` in [bigquery.py:325-342](posthog/temporal/data_imports/sources/bigquery/bigquery.py)
  - Estimates rows using query plan or table metadata
  - Returns in `SourceResponse`

- **MongoDB** ✅ - `_get_rows_to_sync()` in [mongo.py:294-302](posthog/temporal/data_imports/sources/mongodb/mongo.py)
  - Uses `collection.count_documents(query)` to get exact count
  - Returns in `SourceResponse`

- **MSSQL** ✅ - `_get_rows_to_sync()` in [mssql.py:399-420](posthog/temporal/data_imports/sources/mssql/mssql.py)
  - Executes COUNT query on filtered data
  - Returns in `SourceResponse`

- **MySQL** ✅ - `_get_rows_to_sync()` in [mysql.py:129-150](posthog/temporal/data_imports/sources/mysql/mysql.py)
  - Executes COUNT query on filtered data
  - Returns in `SourceResponse`

- **Postgres** ✅ - `_get_rows_to_sync()` in [postgres.py:357-382](posthog/temporal/data_imports/sources/postgres/postgres.py)
  - Executes COUNT query on filtered data
  - Returns in `SourceResponse`

- **Snowflake** ✅ - `_get_rows_to_sync()` in [snowflake.py:172-184](posthog/temporal/data_imports/sources/snowflake/snowflake.py)
  - Executes COUNT query on filtered data
  - Returns in `SourceResponse`

**Not Implemented:** All API sources and non-database sources

**Purpose:** The `rows_to_sync` value is used for progress tracking during the actual sync operation, showing users how many rows remain to be synced.

### 2. Resumable Source Pattern

Sources that implement `ResumableSource` class (vs `SimpleSource`):

**Implemented:**

- **Stripe** ✅ - Uses `ResumableSource[StripeSourceConfig, StripeResumeConfig]` with `starting_after` cursor

**Not Implemented:** All other sources use `SimpleSource`

### 3. Dynamic Chunking

Sources that implement dynamic chunk size calculation based on table size or other factors:

**Implemented:**

- **Postgres** ✅ - Dynamic chunk size calculation in [postgres.py:247-279](posthog/temporal/data_imports/sources/postgres/postgres.py)
  - Calculates chunk size based on table row count and estimates
  - Uses `chunk_size_override` from schema settings
  - Adjusts based on `DEFAULT_PARTITION_TARGET_SIZE_IN_BYTES`

- **BigQuery** ✅ - Dynamic partitioning logic in [bigquery.py:204-229](posthog/temporal/data_imports/sources/bigquery/bigquery.py)
  - Calculates partition size based on table size estimates
  - Adjusts to target partition size

- **MongoDB** ✅ - Has chunking logic
- **MSSQL** ✅ - Has chunking logic
- **MySQL** ✅ - Has chunking logic
- **Snowflake** ✅ - Has chunking logic

**Not Implemented:** Most API sources use fixed page sizes or default chunking

### 4. PyArrow Table with Custom Schema

Sources that return PyArrow tables with their own schema definitions:

**Implemented:**

- **BigQuery** ✅ - Returns PyArrow table via BigQuery Storage API with custom schema conversion
- **Postgres** ✅ - Uses `table_from_iterator()` to build PyArrow schema from query results
- **MongoDB** ✅ - Returns PyArrow table
- **MSSQL** ✅ - Returns PyArrow table
- **MySQL** ✅ - Returns PyArrow table
- **Snowflake** ✅ - Returns PyArrow table
- **DoIt** ✅ - Uses `build_pyarrow_schema()` and `table_from_iterator()` for custom schema
- **Shopify** ✅ - Uses PyArrow schema with custom field definitions
- **Stripe** ✅ - Uses PyArrow with DLT mapping

**Not Implemented:** Sources using DLT Resources return DLT-managed data

### 5. Dynamic Partition Settings

Sources that return dynamic partition configuration in `SourceResponse`:

**Implemented:**

- **Vitally** ✅ - Sets dynamic partition settings in [vitally/source.py:72-82](posthog/temporal/data_imports/sources/vitally/source.py)

  ```python
  partition_count=1,
  partition_size=1,
  partition_mode="datetime",
  partition_format="week",
  partition_keys=["created_at"],
  sort_mode="desc" if schema_name == "Messages" else "asc"
  ```

- **Zendesk** ✅ - Conditional partitioning in [zendesk/source.py:115-124](posthog/temporal/data_imports/sources/zendesk/source.py)
  - Only sets partition settings if endpoint has partition fields
  - Uses week-based datetime partitioning

**Not Implemented:** Most sources don't set explicit partition settings

### 6. REST Source Abstraction

Sources using the `rest_api_resources` / `rest_api_source` abstraction:

**Implemented (9 sources):**

- **Chargebee** - Uses REST source via `rest_api_resources`
- **Reddit Ads** - Uses REST source
- **Salesforce** - Uses REST source
- **TikTok Ads** - Uses REST source
- **Vitally** - Uses REST source
- **Zendesk** - Uses REST source

**Using DLT Resources Directly (3 sources):**

- **Hubspot** - Uses traditional DLT resource with `dlt_source_to_source_response`
- **Chargebee** - Also uses `dlt_source_to_source_response` wrapper

**Custom Implementation:** All database sources and Stripe, Shopify, DoIt, Google Sheets, Bing Ads, Google Ads, LinkedIn Ads, Meta Ads

### 7. No Implementation / Stubs

Sources with `unreleasedSource=True` or stub implementations:

**Stub Sources (11):**

1. **Ashby** - Has TODO comments, raises `NotImplementedError`
2. **Braze** - Empty implementation, `unreleasedSource=True`
3. **Customer.io** - Has TODO comments, raises `NotImplementedError`
4. **GitHub** - Has TODO comments, raises `NotImplementedError`
5. **Klaviyo** - Empty implementation, `unreleasedSource=True`
6. **Mailchimp** - Empty implementation, `unreleasedSource=True`
7. **Mailjet** - Empty implementation, `unreleasedSource=True`
8. **Polar** - Empty implementation, `unreleasedSource=True`
9. **Redshift** - Empty implementation, `unreleasedSource=True`
10. **RevenueCat** - Empty implementation, `unreleasedSource=True`

## Implementation Patterns

### Base Classes

- **SimpleSource[ConfigType]**: Standard source base class (30 sources)
  - Implements `source_for_pipeline(config, inputs) -> SourceResponse`

- **ResumableSource[ConfigType, ResumableData]**: For resumable full-refresh (1 source)
  - Stripe only
  - Adds `get_resumable_source_manager()` method
  - Tracks resume state across runs

### Source Response Types

1. **PyArrow-based** (Database sources + DoIt, Shopify, Stripe)
   - Return iterator of PyArrow tables
   - Full schema control
   - Better performance for large datasets

2. **DLT Resource-based** (Hubspot, Salesforce, Chargebee)
   - Use `dlt_source_to_source_response()` wrapper
   - Leverage DLT's built-in functionality
   - Schema inferred by DLT

3. **REST API-based** (Reddit Ads, TikTok Ads, Vitally, Zendesk)
   - Use `rest_api_resources()` pattern
   - Declarative endpoint configuration
   - Built-in pagination and incremental support

4. **Custom Iterators** (Google Sheets, Bing Ads, LinkedIn Ads, Meta Ads)
   - Custom pagination logic
   - Direct API client usage
   - Manual schema handling

### Authentication Patterns

- **OAuth Integration**: Bing Ads, Google Ads, Hubspot, LinkedIn Ads, Meta Ads, Reddit Ads, Salesforce, TikTok Ads
- **API Key**: Chargebee, DoIt, Shopify, Stripe, Vitally, Zendesk, Google Sheets
- **Service Account / Key File**: BigQuery, Google Ads (alternative)
- **Database Credentials**: All database sources
- **SSH Tunnel Support**: MSSQL, MySQL, Postgres

### Incremental Support

**Database Sources:**

- Filter incremental fields by type (timestamp, date, integer)
- Support incremental and append modes
- Pass incremental field values to queries

**API Sources:**

- Most support incremental via cursor-based pagination
- Some use timestamp-based filtering (DoIt, Vitally)
- REST sources use built-in incremental params

### Error Handling

Most sources define `get_non_retryable_errors()` with common failure patterns:

- Authentication failures
- Permission errors
- Resource not found
- Account suspended/expired
- Rate limiting (varies by source)

## Special Cases

### BigQuery

- Most complex database source
- Uses BigQuery Storage API for efficient reads
- Temp table creation and cleanup
- Custom region and project support
- Dynamic partitioning based on table size

### Stripe

- Only resumable source
- Custom nested resource handling
- Invoice line items expansion
- Batched processing
- Multiple resource types (normal vs nested)

### Shopify

- GraphQL-based (not REST)
- Custom pagination with cursor
- Permission validation
- Retry logic for rate limits

### Postgres/Supabase

- Supabase inherits from Postgres
- SSH tunnel support
- Row count estimation
- Dynamic chunking
- Most complete database implementation

### DoIt

- Custom hash-based primary key generation
- PyArrow schema building
- Timestamp-based incremental
- List reports API

### Vitally

- Custom partition settings per endpoint
- Messages endpoint has different sort order
- REST API-based with custom response handling

## Summary Statistics

| Feature | Count |
|---------|-------|
| Total Sources | 33 |
| Database Sources | 9 |
| API Sources | 24 |
| Fully Implemented | 22 |
| Stub/Unreleased | 11 |
| OAuth-based | 8 |
| API Key-based | 6 |
| SSH Tunnel Support | 3 |
| ResumableSource | 1 |
| PyArrow Tables | 9 |
| DLT Resources | 3 |
| REST API Pattern | 6 |
| Row Count Support (Schema) | 1 |
| Rows to Sync (Runtime) | 6 |
| Dynamic Chunking | 6 |
| Dynamic Partitioning | 2 |

## Beta/Released Status

**Beta Sources:**

- Bing Ads (`featureFlag: "bing-ads-source"`)
- Google Ads
- Google Sheets
- LinkedIn Ads
- Meta Ads (`featureFlag: "meta-ads-dwh"`)
- MongoDB
- Shopify (`featureFlag: "shopify-dwh"`)
- Supabase (`featureFlag: "supabase-dwh"`)

**Featured Sources** (shown prominently in UI):

- Google Sheets
- Hubspot
- Postgres
- Stripe
