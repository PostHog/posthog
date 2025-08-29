# HogQL Timestamp Optimization Implementation Plan

## Executive Summary
This document outlines the plan to optimize HogQL SQL generation by automatically adding `toDate(timestamp)` conditions to queries against the `events` table. For each existing condition on the `timestamp` column, we will add a corresponding condition on `toDate(timestamp)` that checks only the date portion. This optimization leverages the existing ClickHouse index on `(team_id, toDate(timestamp), event, cityHash64(distinct_id), cityHash64(uuid))` to significantly improve query performance.

## Problem Statement
Currently, HogQL queries against the events table that filter on timestamp do not include corresponding `toDate(timestamp)` conditions. Without these date-level conditions, ClickHouse cannot efficiently use the primary index, leading to slower query execution times and higher resource consumption.

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
- Traverse the AST to identify SELECT queries with events table
- Find all conditions on the `timestamp` column
- For each timestamp condition, generate a corresponding `toDate(timestamp)` condition
- Add the date conditions to the WHERE clause without modifying existing conditions

**Key Classes**:
```python
class TimestampConditionTransformer(TraversingVisitor):
    """
    For each condition on timestamp column in events table queries,
    adds a corresponding toDate(timestamp) condition checking only the date.
    """
    
    def visit_select_query(self, node: ast.SelectQuery):
        if self._uses_events_table(node):
            timestamp_conditions = self._find_timestamp_conditions(node)
            for condition in timestamp_conditions:
                date_condition = self._create_date_condition(condition)
                self._add_condition_to_where(node, date_condition)
        return node
    
    def _uses_events_table(self, node: ast.SelectQuery) -> bool:
        # Check if events table is referenced in FROM clause
        pass
    
    def _find_timestamp_conditions(self, node: ast.SelectQuery) -> List[ast.Expr]:
        # Find all conditions that filter on timestamp column
        pass
    
    def _create_date_condition(self, timestamp_condition: ast.Expr) -> ast.Expr:
        # Convert timestamp condition to corresponding toDate condition
        # e.g., timestamp > '2024-01-01' -> toDate(timestamp) >= toDate('2024-01-01')
        pass
    
    def _add_condition_to_where(self, node: ast.SelectQuery, condition: ast.Expr):
        # Add the date condition to WHERE clause using AND
        pass
```

#### 1.2 Condition Analysis Utilities
**File**: `posthog/hogql/helpers/timestamp_visitor.py`

**New Functions**:
- `extract_timestamp_field()`: Check if an expression references the timestamp column
- `convert_operator_for_date()`: Convert timestamp operators to appropriate date operators
- `create_todate_condition()`: Generate `toDate(timestamp)` condition from timestamp condition

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

#### 3.1 Condition Transformation Logic
The transformer will follow these rules:

1. **Detection Phase**:
   - Check if the SELECT query's table is `events`
   - Find all WHERE conditions that reference the `timestamp` column

2. **Transformation Phase**:
   - For each timestamp condition found, create a corresponding `toDate(timestamp)` condition
   - Convert operators appropriately (e.g., `>` becomes `>=`, `<` becomes `<=` for date boundaries)
   - Preserve the original timestamp conditions unchanged

3. **Integration Phase**:
   - Add the new date conditions to the WHERE clause using AND logic
   - Ensure conditions are properly parenthesized
   - Maintain query semantics and correctness

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

#### Simple Timestamp Filter
```sql
-- Before
SELECT count(*) 
FROM events 
WHERE timestamp > '2024-01-01 10:30:00'

-- After  
SELECT count(*) 
FROM events 
WHERE timestamp > '2024-01-01 10:30:00'
  AND toDate(timestamp) >= toDate('2024-01-01 10:30:00')
```

#### Range Query Example
```sql
-- Before
SELECT event, count(*) 
FROM events 
WHERE timestamp >= '2024-01-01' 
  AND timestamp < '2024-02-01'
  AND event = 'pageview'

-- After
SELECT event, count(*) 
FROM events 
WHERE timestamp >= '2024-01-01' 
  AND timestamp < '2024-02-01'
  AND event = 'pageview'
  AND toDate(timestamp) >= toDate('2024-01-01')
  AND toDate(timestamp) < toDate('2024-02-01')
```

#### Complex Query with JOIN
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
GROUP BY event
```

## Conclusion

This implementation plan provides a structured approach to optimizing HogQL queries through intelligent timestamp condition injection. By ensuring all events table queries include `toDate(timestamp)` conditions, we can significantly improve query performance while maintaining backward compatibility and system stability.

The phased approach allows for careful validation at each step, with comprehensive testing and gradual rollout to minimize risk. Success will be measured through concrete performance metrics and user satisfaction.