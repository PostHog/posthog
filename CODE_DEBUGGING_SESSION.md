# Web Analytics Pre-Aggregated Tables Backfill Analysis

## Issue Summary

Analysis of the outdated branch `lricoy/web-analytics-backfill-dagster-only` to understand the current backfill approach for web analytics pre-aggregated tables and identify opportunities for simplification using Django model signals + Celery tasks.

## Evidence

### Current Implementation Analysis

**Branch Status**: `lricoy/web-analytics-backfill-dagster-only`
- Last commits: "wip" commits indicating incomplete development
- Contains comprehensive Dagster-based backfill system but NOT INTEGRATED into any Dagster location
- The backfill assets/sensors/schedules are defined but not deployed

### Architecture Overview

1. **Team Selection System** - Complex multi-strategy approach:
   - `ProjectSettingsStrategy`: Uses `Team.web_analytics_pre_aggregated_tables_enabled` boolean field
   - `EnvironmentVariableStrategy`: Uses `WEB_ANALYTICS_ENABLED_TEAM_IDS` env var
   - `HighPageviewsStrategy`: Automatically selects top 30 teams by median pageviews
   - Default fallback: Hard-coded list of 7 team IDs

2. **Backfill Detection** - Direct ClickHouse query approach:
   - Queries `web_pre_aggregated_stats` and `web_pre_aggregated_bounces` tables directly
   - Compares expected vs existing partitions using CTE queries
   - Implements "80/20 rule" - only triggers backfill for ≥3 missing partitions
   - Default lookback period: 30 days, configurable via `WEB_ANALYTICS_BACKFILL_LOOKBACK_DAYS`

3. **Dagster Infrastructure**:
   - **Asset**: `web_analytics_backfill_detector` - detects missing data
   - **Sensor**: `web_analytics_backfill_sensor` - triggers backfill every 6 hours (STOPPED by default)
   - **Schedule**: `web_analytics_backfill_schedule` - daily backfill check at 2 AM UTC (STOPPED by default)
   - **Jobs**: Manual diagnostic jobs (`check_missing_data_job`, `show_data_gaps_job`)

4. **Staging Table Strategy** - Current pre-aggregation uses complex partition swapping:
   - Uses staging tables (`web_pre_aggregated_stats_staging`, `web_pre_aggregated_bounces_staging`)
   - Process: Drop staging partitions → Generate hourly data → Swap partitions → Cleanup
   - Risk of partition swap failures mentioned by user as concern

## Root Cause Analysis

### Technical Debt and Complexity Issues

1. **Over-Engineered Team Selection**:
   - Three different strategies with complex configuration via environment variables
   - ClickHouse dictionary system for team lookup adds operational complexity
   - Hard-coded default team IDs that need manual maintenance

2. **Dagster Integration Gaps**:
   - Backfill components exist but are not integrated into any Dagster location
   - Sensors and schedules are disabled by default indicating lack of production readiness
   - Complex sensor/schedule logic that duplicates detection functionality

3. **Query-Based Detection Overhead**:
   - Direct ClickHouse queries for each detection run
   - Complex CTE queries that need to scan partition metadata
   - No caching or state management

4. **Partition Management Complexity**:
   - Multiple partition operations per backfill (drop, swap, cleanup)
   - Risk of data loss during partition swaps
   - Complex staging table management

5. **Configuration Sprawl**:
   - Multiple environment variables for tuning behavior
   - Different settings for lookback days, partition limits, timeouts
   - Configuration spread across multiple strategies

## Steps Taken

1. **Codebase Analysis**:
   - Examined all backfill-related files in `dags/` directory
   - Analyzed team selection strategies and their implementations
   - Reviewed Dagster assets, sensors, schedules, and jobs
   - Checked integration points and dependencies

2. **Architecture Review**:
   - Mapped data flow from team flag changes to backfill execution
   - Identified all configuration points and environment variables
   - Analyzed staging table operations and partition management
   - Reviewed error handling and retry mechanisms

3. **Comparison with Master**:
   - Confirmed `Team.web_analytics_pre_aggregated_tables_enabled` field exists on master
   - Verified backfill components are not deployed (not in Dagster locations)
   - Identified that only formatting/import changes exist between branches

## Comparison with Master Branch

### Key Differences:
- **New Files**: `dags/web_preaggregated_backfill.py`, `dags/tests/test_web_preaggregated_backfill.py`
- **No Integration**: Backfill assets not added to `dags/locations/web_analytics.py`
- **Import Reordering**: Mass import reorganization across all DAG files (not functional changes)
- **Team Model Field**: `web_analytics_pre_aggregated_tables_enabled` exists on both branches

### No Conflicts Expected:
- Team model field already exists on master
- New backfill files don't conflict with existing code
- Import changes are cosmetic and should merge cleanly

## Solution Recommendation

### Proposed Django Model Signal + Celery Approach

**Benefits over current Dagster approach**:

1. **Immediate Reaction**: Signal fires immediately when team enables pre-aggregated tables
2. **Simpler Logic**: Single trigger point, no complex detection queries needed
3. **Built-in Retry**: Celery provides robust retry mechanisms
4. **Lower Overhead**: No periodic scanning or complex partition queries
5. **Better Integration**: Uses existing Django/Celery infrastructure

### Implementation Approach:

```python
# In posthog/models/team/team.py
@receiver(post_save, sender=Team)
def trigger_web_analytics_backfill(sender, instance, **kwargs):
    if instance.web_analytics_pre_aggregated_tables_enabled:
        # Check if this is a new enablement
        if 'web_analytics_pre_aggregated_tables_enabled' in kwargs.get('update_fields', []):
            from posthog.tasks.web_analytics import backfill_team_pre_aggregated_data
            backfill_team_pre_aggregated_data.delay(instance.id)

# New Celery task
@shared_task(bind=True, max_retries=3)
def backfill_team_pre_aggregated_data(self, team_id):
    # Simple last 7 days backfill for the specific team
    # Much simpler than current multi-table detection approach
    pass
```

## Verification Plan

1. **Test Signal Integration**: Verify signals fire correctly when team flag changes
2. **Validate Backfill Logic**: Ensure 7-day backfill works for newly enabled teams
3. **Monitor Performance**: Compare resource usage vs current Dagster approach
4. **Error Handling**: Test Celery retry mechanisms and failure scenarios

## Prevention Measures

1. **Simplify Team Selection**: Use only Django model field, remove complex strategies
2. **Remove Staging Tables**: Use direct INSERT operations instead of partition swapping
3. **Eliminate Configuration Sprawl**: Hardcode sensible defaults (7-day backfill)
4. **Standard Django Patterns**: Use existing PostHog signal/task patterns

## Technical Debt Summary

The current Dagster-based backfill system represents significant over-engineering:

- **350+ lines of backfill detection logic** vs simple model signal
- **Complex multi-strategy team selection** vs single boolean field check
- **Partition swapping operations** vs direct data insertion
- **Multiple environment variables** vs hardcoded sensible defaults
- **Dagster sensors/schedules** vs immediate signal-based triggering

**Recommendation**: Abandon the current Dagster approach and implement the simpler Django signal + Celery task pattern for automatic backfills with minimal changes to existing codebase.

## Files Analyzed

- `/Users/lricoy/.worktrees/posthog/lricoy/web-analytics-backfill/dags/web_preaggregated_backfill.py`
- `/Users/lricoy/.worktrees/posthog/lricoy/web-analytics-backfill/dags/web_preaggregated_team_selection.py`
- `/Users/lricoy/.worktrees/posthog/lricoy/web-analytics-backfill/posthog/models/web_preaggregated/team_selection_strategies.py`
- `/Users/lricoy/.worktrees/posthog/lricoy/web-analytics-backfill/dags/web_preaggregated.py`
- `/Users/lricoy/.worktrees/posthog/lricoy/web-analytics-backfill/posthog/models/web_preaggregated/team_selection.py`
- `/Users/lricoy/.worktrees/posthog/lricoy/web-analytics-backfill/posthog/models/team/team.py`
- `/Users/lricoy/.worktrees/posthog/lricoy/web-analytics-backfill/docs/web_analytics_backfill.md`
- `/Users/lricoy/.worktrees/posthog/lricoy/web-analytics-backfill/dags/web_preaggregated_utils.py`