# HogQL Timestamp Optimization Implementation Plan

## Executive Summary
This document outlines the plan to refactor the HogQL SQL generator to ensure that all queries against the `events` table include a `toDate(timestamp)` condition. This optimization will leverage the existing ClickHouse index on `(team_id, toDate(timestamp), event, cityHash64(distinct_id), cityHash64(uuid))` to significantly improve query performance.

## Problem Statement
Currently, HogQL queries against the events table may not always include a `toDate(timestamp)` condition in their WHERE clause. Without this condition, ClickHouse cannot efficiently use the primary index, leading to slower query execution times and higher resource consumption.

## Technical Background

### Current Index Structure
The events table has a compound index defined as:
```sql
ORDER BY (team_id, toDate(timestamp), event, cityHash64(distinct_id), cityHash64(uuid))
```
Location: `posthog/models/event/sql.py:129`

### Key Components
1. **Events Table Schema**: `posthog/hogql/database/schema/events.py`
2. **SQL Generation**: `posthog/hogql/printer.py`
3. **Query Execution**: `posthog/hogql/query.py`
4. **Timestamp Utilities**: `posthog/hogql/helpers/timestamp_visitor.py`

## Implementation Strategy

### Phase 1: Core Transformer Development

#### 1.1 Create Timestamp Condition Transformer
**File**: `posthog/hogql/transforms/timestamp_condition.py`

**Responsibilities**:
- Traverse the AST to identify queries using the events table
- Check for existing `toDate(timestamp)` conditions
- Inject optimized conditions when missing
- Handle complex query patterns (joins, subqueries, CTEs)

**Key Classes**:
```python
class TimestampConditionTransformer(TraversingVisitor):
    """
    Ensures all events table queries include toDate(timestamp) conditions
    for optimal index usage.
    """
    
    def visit_select_query(self, node: ast.SelectQuery):
        # Implementation details
        pass
    
    def _has_events_table(self, node: ast.SelectQuery) -> bool:
        # Check if events table is referenced
        pass
    
    def _has_todate_condition(self, node: ast.SelectQuery) -> bool:
        # Check for existing toDate conditions
        pass
    
    def _inject_todate_condition(self, node: ast.SelectQuery) -> ast.SelectQuery:
        # Add the condition to WHERE clause
        pass
```

#### 1.2 Enhance Timestamp Detection
**File**: `posthog/hogql/helpers/timestamp_visitor.py`

**New Functions**:
- `extract_timestamp_range()`: Extract date ranges from existing conditions
- `has_todate_condition()`: Check for toDate wrapped conditions
- `create_todate_condition()`: Generate optimized toDate conditions

### Phase 2: Pipeline Integration

#### 2.1 Modify Query Preparation Pipeline
**File**: `posthog/hogql/printer.py`

**Location**: `prepare_ast_for_printing()` function, around line 150

**Changes**:
```python
if dialect == "clickhouse":
    with context.timings.measure("resolve_property_types"):
        # ... existing code ...
    
    # NEW: Add timestamp condition optimization
    with context.timings.measure("optimize_timestamp_conditions"):
        from posthog.hogql.transforms.timestamp_condition import optimize_timestamp_conditions
        node = optimize_timestamp_conditions(node, context)
```

#### 2.2 Configuration Management
**File**: `posthog/hogql/modifiers.py` or `posthog/schema.py`

**Add Configuration**:
```python
class HogQLQueryModifiers:
    # ... existing fields ...
    optimizeTimestampConditions: bool = True  # Default enabled
```

### Phase 3: Implementation Details

#### 3.1 Condition Injection Logic
The transformer will follow these rules:

1. **Detection Phase**:
   - Identify if `events` table is in FROM clause
   - Check for existing timestamp conditions
   - Analyze query date range requirements

2. **Injection Phase**:
   - If no date condition exists, add a reasonable default (e.g., last 30 days)
   - If timestamp conditions exist but no toDate, wrap them appropriately
   - Preserve existing conditions while adding optimization

3. **Optimization Phase**:
   - Combine multiple date conditions when possible
   - Use the most restrictive date range
   - Ensure conditions align with index structure

#### 3.2 Edge Cases to Handle
- Queries with JOIN operations involving events table
- Subqueries and CTEs
- UNION queries
- Queries with OR conditions
- Parameterized queries with placeholders

### Phase 4: Testing Strategy

#### 4.1 Unit Tests
**File**: `posthog/hogql/transforms/test/test_timestamp_condition.py`

**Test Cases**:
- Query without any date conditions
- Query with existing timestamp conditions
- Query with existing toDate conditions
- Complex queries with joins
- Subqueries and CTEs
- Edge cases and error conditions

#### 4.2 Integration Tests
**Files**: Update existing test files in `posthog/hogql/test/`

**Validation**:
- End-to-end query generation
- Performance benchmarks
- Backward compatibility
- Feature flag behavior

#### 4.3 Performance Testing
- Benchmark queries before and after optimization
- Measure index usage improvements
- Monitor query execution times
- Validate resource consumption reduction

### Phase 5: Rollout Plan

#### 5.1 Feature Flag Implementation
```python
# Initial rollout with feature flag
if context.modifiers.optimizeTimestampConditions:
    node = optimize_timestamp_conditions(node, context)
```

#### 5.2 Gradual Rollout
1. **Week 1**: Enable for internal testing
2. **Week 2**: Enable for 10% of queries
3. **Week 3**: Enable for 50% of queries
4. **Week 4**: Full rollout if metrics are positive

#### 5.3 Monitoring
- Query performance metrics
- Error rates
- Index usage statistics
- Customer feedback

## Risk Assessment

### Identified Risks

1. **Query Breakage**
   - **Risk**: Existing queries might fail with new conditions
   - **Mitigation**: Comprehensive testing, feature flag for rollback

2. **Performance Regression**
   - **Risk**: Some queries might perform worse with additional conditions
   - **Mitigation**: Smart detection to avoid redundant conditions

3. **Complex Query Handling**
   - **Risk**: Edge cases in complex queries might not be handled correctly
   - **Mitigation**: Extensive testing, gradual rollout

4. **Backward Compatibility**
   - **Risk**: Changes might affect existing integrations
   - **Mitigation**: Feature flag, versioning strategy

## Success Metrics

### Primary Metrics
- **Query Performance**: 30-50% reduction in average query time for events table queries
- **Index Usage**: 95%+ of events queries using the primary index
- **Resource Usage**: 20-30% reduction in CPU and memory consumption

### Secondary Metrics
- **Error Rate**: No increase in query failures
- **Customer Satisfaction**: No negative feedback on query performance
- **Code Quality**: Maintain or improve test coverage

## Timeline

### Week 1-2: Development
- Implement core transformer
- Add timestamp detection utilities
- Initial unit tests

### Week 3: Integration
- Integrate with query pipeline
- Add configuration options
- Comprehensive testing

### Week 4: Testing & Optimization
- Performance benchmarking
- Edge case handling
- Documentation

### Week 5-6: Rollout
- Gradual feature flag rollout
- Monitoring and adjustments
- Full deployment

## Documentation Requirements

### Code Documentation
- Inline comments explaining logic
- Docstrings for all public functions
- Type hints for all parameters

### User Documentation
- Update HogQL documentation
- Performance tuning guide
- Migration notes for existing queries

## Appendix

### Example Transformations

#### Before Optimization
```sql
SELECT count(*) 
FROM events 
WHERE event = 'pageview'
```

#### After Optimization
```sql
SELECT count(*) 
FROM events 
WHERE event = 'pageview' 
  AND toDate(timestamp) >= today() - 30
  AND toDate(timestamp) <= today()
```

#### Complex Query Example
```sql
-- Before
SELECT event, count(*) 
FROM events e
JOIN persons p ON e.person_id = p.id
WHERE e.timestamp > '2024-01-01'
GROUP BY event

-- After
SELECT event, count(*) 
FROM events e
JOIN persons p ON e.person_id = p.id
WHERE e.timestamp > '2024-01-01'
  AND toDate(e.timestamp) >= toDate('2024-01-01')
  AND toDate(e.timestamp) <= today()
GROUP BY event
```

## Conclusion

This implementation plan provides a structured approach to optimizing HogQL queries through intelligent timestamp condition injection. By ensuring all events table queries include `toDate(timestamp)` conditions, we can significantly improve query performance while maintaining backward compatibility and system stability.

The phased approach allows for careful validation at each step, with comprehensive testing and gradual rollout to minimize risk. Success will be measured through concrete performance metrics and user satisfaction.