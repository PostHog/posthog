# Version Execution Tracking Plan

## Current State
- Endpoints usage tracking exists in the Usage tab
- Breakdowns available: Endpoint, MaterializationType, ApiKey, Status
- No version-specific tracking currently available

## Requirements
Track which versions of endpoints are being executed via the API to:
1. Understand version adoption (are users still calling old versions?)
2. Identify if materialization settings for old versions are effective
3. Plan deprecation of old versions
4. Debug version-specific performance issues

## Implementation Approach

### Phase 1: Backend - Version Tracking in Query Log
**Files to modify:**
- `posthog/api/endpoints.py` - Capture version in execution context
- `posthog/hogql_queries/endpoints/endpoints_usage_query_runner.py` - Add version breakdown support

**Changes needed:**
1. Ensure endpoint execution logs include the version number
2. Add version field to the query_log context or create a new tracking table
3. Update execution runner to extract version from request

### Phase 2: Schema Updates
**Files to modify:**
- `posthog/schema.py` - Add `VERSION = "Version"` to `EndpointsUsageBreakdown` enum
- `frontend/src/queries/schema/schema-general.ts` - Add `Version` to enum
- Run schema generation: `pnpm --filter=@posthog/frontend generate:schema`

**Schema changes:**
```python
class EndpointsUsageBreakdown(StrEnum):
    ENDPOINT = "Endpoint"
    MATERIALIZATION_TYPE = "MaterializationType"
    API_KEY = "ApiKey"
    STATUS = "Status"
    VERSION = "Version"  # NEW
```

### Phase 3: Frontend - Add Version Breakdown
**Files to modify:**
- `products/endpoints/frontend/EndpointsUsageFilters.tsx` - Add version breakdown option
- `products/endpoints/frontend/EndpointsUsage.tsx` - Add version column rendering if needed

**Changes:**
```typescript
// In EndpointsUsageFilters.tsx breakdown options:
{ value: EndpointsUsageBreakdown.Version, label: 'By version' },

// In EndpointsUsage.tsx table context:
version: {
    title: 'Version',
    render: ({ value }) => <span>v{value}</span>,
},
```

### Phase 4: Backend Query Runner
**File:** `posthog/hogql_queries/endpoints/endpoints_usage_query_runner.py`

**Add to `_get_breakdown_expression` method:**
```python
elif breakdown == EndpointsUsageBreakdown.VERSION:
    return ast.Field(chain=["endpoint_version"]), "version"
```

## Open Questions
1. Where is the version currently stored during endpoint execution?
   - Need to check if it's in the API request context
   - Verify if query_log captures this information

2. Do we need a separate table for version tracking or can we use query_log?
   - query_log might be sufficient if we add version to the context
   - Consider retention policies for query_log data

3. Should we track version in:
   - API request parameters (explicit `?version=2`)
   - Endpoint routing/execution layer
   - Both?

## Testing Plan
1. Execute different endpoint versions via API
2. Verify version appears in usage breakdown
3. Test filtering by specific versions
4. Verify charts show version breakdown correctly

## Migration Considerations
- Existing execution logs won't have version data
- Need to handle null/missing version gracefully
- Consider backfilling if version can be inferred from historical data

## Priority
Medium - Useful for production deployments but not blocking for initial version history feature

## Next Steps
1. Investigate where endpoint version is currently captured during execution
2. Determine if backend changes are needed to track version
3. Implement schema changes
4. Add frontend breakdown option
5. Test end-to-end
