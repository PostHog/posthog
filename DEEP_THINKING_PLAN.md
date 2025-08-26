# Deep Thinking Plan: Automatic Web Analytics Pre-Aggregated Tables Backfill

## Executive Summary

**Objective**: Replace the over-engineered, undeployed Dagster backfill system with a simple, reliable Django signal + Celery task approach for automatic 7-day backfills when teams enable pre-aggregated tables.

**Core Insight**: The current 350+ line Dagster solution is not deployed and adds unnecessary complexity. A ~50 line Django signal + Celery task can achieve the same goal with better reliability and instant response to team setting changes.

## Current State Analysis

### Problems with Existing Approach
1. **Over-engineered**: 350+ lines of Dagster logic with 3 team selection strategies
2. **Not Production-Ready**: Complex system but NOT INTEGRATED into any Dagster location
3. **Risky Partition Swaps**: Uses staging tables with partition swapping operations
4. **Configuration Sprawl**: Multiple environment variables and complex tuning parameters
5. **Delayed Response**: Periodic scanning instead of immediate action on team setting changes

### What We Have Available
✅ **Team Model Field**: `web_analytics_pre_aggregated_tables_enabled = models.BooleanField(default=False, null=True)`  
✅ **Target Tables**: `web_pre_aggregated_stats` and `web_pre_aggregated_bounces`  
✅ **Celery Infrastructure**: PostHog uses `@shared_task` pattern extensively  
✅ **Data Pipeline**: Existing DAGs generate hourly pre-aggregated data  

## Proposed Solution Architecture

### High-Level Flow
```
Team.web_analytics_pre_aggregated_tables_enabled = True
    ↓ (Django post_save signal)
backfill_web_analytics_tables.delay(team_id)
    ↓ (Celery task)
Single ClickHouse INSERT query (last 7 days)
    ↓ (Success/Failure)
Optional: Safety cleanup mechanism
```

### Core Components

#### 1. Django Signal Handler
- **Location**: `posthog/models/team/signals.py` (new file)
- **Trigger**: `post_save` signal on Team model
- **Condition**: `web_analytics_pre_aggregated_tables_enabled` changed from False/None to True
- **Action**: Async trigger Celery task with team_id

#### 2. Celery Backfill Task
- **Location**: `posthog/tasks/web_analytics_backfill.py` (new file)  
- **Strategy**: Direct INSERT without partition swaps
- **Scope**: Last 7 days of data
- **Safety**: Built-in Celery retry mechanism + custom error handling

#### 3. Safety Mechanism (Risk Mitigation)
- **Option A**: Daily cleanup task to DELETE corrupted data
- **Option B**: Disable tables daily and re-enable after validation
- **Option C**: Data validation checks before marking backfill complete

## Implementation Strategy - Minimal Changes

### Phase 1: Core Implementation (~50 lines)
```python
# posthog/models/team/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from posthog.tasks.web_analytics_backfill import backfill_web_analytics_tables

@receiver(post_save, sender=Team)
def handle_web_analytics_enable(sender, instance, **kwargs):
    if kwargs.get('update_fields') and 'web_analytics_pre_aggregated_tables_enabled' in kwargs['update_fields']:
        if instance.web_analytics_pre_aggregated_tables_enabled:
            backfill_web_analytics_tables.delay(instance.id)

# posthog/tasks/web_analytics_backfill.py
from celery import shared_task
from posthog.clickhouse.client import sync_execute

@shared_task(bind=True, max_retries=3)
def backfill_web_analytics_tables(self, team_id: int):
    try:
        # Single query to backfill last 7 days
        sync_execute(BACKFILL_QUERY, {"team_id": team_id})
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60)
```

### Phase 2: Safety Mechanisms
```python
@shared_task
def validate_backfill_data(team_id: int):
    # Compare expected vs actual row counts
    # Validate data integrity
    # Disable tables if validation fails

@shared_task
def daily_web_analytics_cleanup():
    # Option A: Clean up corrupted data
    # Option B: Disable/re-enable tables with validation
```

### Phase 3: Monitoring & Observability
```python
# Add structured logging
# PostHog event tracking for backfill success/failure
# Slack alerts for failed backfills
```

## Risk Analysis & Mitigation

### Primary Risk: Direct INSERT without Partition Swap
**Risk**: Data corruption or duplicate rows if backfill runs multiple times
**Mitigation Options**:
1. **Idempotent Design**: Use REPLACE INTO or INSERT ... ON DUPLICATE KEY
2. **Pre-flight Check**: Verify no existing data before backfill
3. **Atomic Operations**: Use transactions where possible
4. **Daily Validation**: Automated data integrity checks

### Secondary Risk: Task Failures
**Risk**: Celery task failures leaving teams in inconsistent state  
**Mitigation**: 
- Built-in retry mechanism (max_retries=3)
- Dead letter queue for manual intervention
- Fallback to disable tables on repeated failures

### Operational Risk: Scale
**Risk**: Many teams enabling simultaneously causing database load
**Mitigation**:
- Rate limiting on Celery task
- Queue management (separate queue for backfill tasks)
- Monitoring and alerting on task queue depth

## Success Metrics

### Performance Metrics
- **Backfill Completion Time**: Target <5 minutes for 7 days of data
- **Success Rate**: >95% successful backfills
- **Resource Usage**: <10% increase in ClickHouse CPU during backfill

### Business Metrics  
- **Adoption**: Teams enabling pre-aggregated tables
- **Data Quality**: Zero data inconsistencies detected
- **Developer Experience**: Reduced complexity from 350 lines to ~50 lines

## Implementation Timeline

### Week 1: Core Implementation
- [ ] Create Django signal handler
- [ ] Implement basic Celery task
- [ ] Write backfill ClickHouse query
- [ ] Basic error handling and logging

### Week 2: Safety & Testing
- [ ] Add data validation mechanisms
- [ ] Implement safety cleanup task
- [ ] Unit tests and integration tests
- [ ] Performance testing with production data

### Week 3: Monitoring & Deployment
- [ ] Add observability (logging, metrics, alerts)
- [ ] Feature flag for gradual rollout
- [ ] Documentation and runbook
- [ ] Deploy to staging environment

### Week 4: Production Rollout
- [ ] Gradual rollout with feature flag
- [ ] Monitor success/failure rates
- [ ] Cleanup old Dagster code
- [ ] Post-mortem and lessons learned

## Technical Deep Dive

### The Backfill Query Strategy
```sql
-- Single query approach - directly populate both tables
INSERT INTO web_pre_aggregated_stats 
SELECT 
    -- Aggregated pageview data for last 7 days
    team_id,
    toStartOfDay(timestamp) as period_bucket,
    -- ... other aggregated fields
FROM events 
WHERE team_id = {team_id}
    AND timestamp >= now() - INTERVAL 7 DAY
    AND event IN ('$pageview', '$screen')
GROUP BY team_id, period_bucket, -- other grouping fields
```

### Signal Detection Logic
```python
def has_field_changed(instance, field_name):
    """Check if specific field changed from False/None to True"""
    if not instance.pk:
        return False  # New object
    
    try:
        old_instance = Team.objects.get(pk=instance.pk)
        old_value = getattr(old_instance, field_name)
        new_value = getattr(instance, field_name)
        
        return not old_value and new_value
    except Team.DoesNotExist:
        return False
```

### Error Recovery Strategy
```python
class BackfillError(Exception):
    """Custom exception for backfill failures"""
    pass

def rollback_backfill(team_id: int):
    """Rollback mechanism for failed backfills"""
    # Option 1: DELETE backfilled data
    # Option 2: Disable pre-aggregated tables
    # Option 3: Mark for manual review
```

## Migration Strategy

### From Current State
1. **No Impact**: Current Dagster system is not deployed, so no migration needed
2. **Clean Slate**: Implement new system independently 
3. **Gradual Rollout**: Use feature flag to control which teams get auto-backfill

### Future Enhancements
1. **Configurable Backfill Period**: Allow teams to choose 7/14/30 days
2. **Smart Backfill**: Only backfill missing date ranges
3. **Real-time Backfill**: Stream processing for immediate backfill
4. **Cross-Region Support**: Handle teams across different ClickHouse clusters

## Decision Framework

### Go/No-Go Criteria
**GO**: 
- ✅ Reduces complexity from 350+ lines to ~50 lines
- ✅ Immediate response to team setting changes
- ✅ Uses proven PostHog patterns (signals + Celery)
- ✅ Better error handling and retry mechanisms

**NO-GO**:
- ❌ Data integrity risks too high
- ❌ Performance impact exceeds 10% ClickHouse CPU
- ❌ Success rate below 90% in testing

### Alternative Approaches Considered
1. **Keep Dagster**: Fix integration issues (HIGH effort, MEDIUM value)
2. **Hybrid Approach**: Signals + Dagster (MEDIUM effort, LOW value)  
3. **Manual Process**: Admin-triggered backfills (LOW effort, LOW value)
4. **Real-time Streaming**: Stream processing (HIGH effort, HIGH value, FUTURE)

## Conclusion

The Django signal + Celery task approach provides the optimal balance of simplicity, reliability, and immediate response to team configuration changes. While there are inherent risks with direct INSERT operations, these can be effectively mitigated through proper validation, monitoring, and rollback mechanisms.

**Recommendation**: Proceed with implementation, starting with a minimal viable solution and iterating based on real-world usage patterns.

---

*This plan prioritizes minimal changes for maximum impact, following PostHog's established patterns while significantly reducing system complexity.*