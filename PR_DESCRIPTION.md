# feat(max): Add read_data tool and error tracking artifacts

## Summary

This PR introduces a unified `read_data` tool for Max AI that consolidates reading of insights, dashboards, billing info, and error tracking data. It also adds artifact-based error tracking tools that provide visual UI cards in Max chat alongside actionable data for the agent.

**Key improvements:**
- Max now queries error tracking data from ClickHouse (same as UI), fixing data discrepancy issues
- Error tracking tools create persistent artifacts that render as interactive cards
- Tools return actual issue data to the agent, enabling better follow-up responses
- Refactored context system with reusable `InsightContext`, `DashboardContext`, and `ErrorTrackingContext` classes

## Changes

### Backend

**New Read Data Tool (`ee/hogai/tools/read_data/`)**
- Unified tool for reading various PostHog data types
- Supports: insights, dashboards, billing info, warehouse schema, error tracking issues/filters
- Uses discriminated union pattern for clean query type handling
- Dynamic tool schema based on user permissions (billing access, artifact access)
- Updated `_read_artifacts()` to format all artifact types (visualization, error_tracking_filters, error_tracking_impact)
- Added `_format_artifact_message()` helper with type-specific formatting for each artifact type

**Error Tracking Tools (`products/error_tracking/backend/max_tools.py`)**
- `ErrorTrackingIssueFilteringTool`: Creates filter artifacts AND returns issue list to agent
- `ErrorTrackingIssueImpactTool`: Analyzes issue impact with aggregations and breakdowns
- `ErrorTrackingExplainIssueTool`: Now fetches stacktrace directly from ClickHouse
- Removed taxonomy-agent-based impact flow (replaced with artifact-based approach)

**Artifacts Manager (`ee/hogai/artifacts/manager.py`)**
- New artifact types: `ERROR_TRACKING_FILTERS`, `ERROR_TRACKING_IMPACT`
- Generic result types: `StateArtifactResult`, `DatabaseArtifactResult`, `ModelArtifactResult`
- Factory methods: `create_error_tracking_filters()`, `create_error_tracking_impact()`
- Fixed `aget_conversation_artifact_messages()` to validate artifacts by type (was incorrectly assuming all artifacts are `VisualizationArtifactContent`)
- Added `_validate_artifact_content()` helper that maps each `AgentArtifact.Type` to its correct content model
- Updated `_afetch_artifact_contents()` to handle all artifact types

**Context System Refactor (`ee/hogai/context/`)**
- New `InsightContext` class - handles insight schema formatting and query execution
- New `DashboardContext` class - parallel insight execution with semaphore control
- New `ErrorTrackingFiltersContext` class - executes error tracking filter queries via ClickHouse
- New `ErrorTrackingIssueContext` class - fetches aggregations for specific issues
- Cleaner separation between UI context processing and query execution
- Reusable across read_data tool and error tracking max_tools

### Frontend

**New Artifact Components**
- `ErrorTrackingFiltersArtifactAnswer.tsx` - Displays filter criteria with status/date tags
- `ErrorTrackingImpactArtifactAnswer.tsx` - Shows impact metrics, trends, and breakdowns

**Max Constants Updates**
- Added tool definitions for new error tracking tools
- Enhanced `read_data` subtools with display formatters
- Added `ErrorTracking` mode definition

**Context Logic**
- Support for error tracking issues in taxonomic filter
- New reducers for `contextErrorTrackingIssues`

### Schema

**New Types**
- `ErrorTrackingFiltersArtifactContent` - Filter artifact payload
- `ErrorTrackingImpactArtifactContent` - Impact analysis artifact payload
- `ErrorTrackingImpactSegment` - Breakdown segment data
- `MaxErrorTrackingIssueContext` - Error tracking issue in UI context

**Updated Types**
- `ArtifactContentType` - Added error tracking artifact types
- `ArtifactMessage.content` - Extended union with new content types
- `MaxUIContext` - Added `error_tracking_issue` and `error_tracking_issues`

## Reasoning

### Why a unified read_data tool?
Previously, reading different data types (insights, dashboards, error tracking) used disparate approaches. A unified tool:
- Reduces prompt complexity for the LLM
- Provides consistent error handling
- Makes it easier to add new readable data types

### Why artifact-based error tracking?
The previous approach had two problems:
1. **Data discrepancy**: Max queried Django ORM while the UI queried ClickHouse, leading to different results
2. **No data for agent**: Tools created UI cards but didn't return issue data to the agent

The artifact-based approach:
- Uses `ErrorTrackingQuery` runner (same as UI)
- Creates persistent artifacts for user reference
- Returns structured data to the agent for follow-up actions

### Why refactor the context system?
The original context processing had:
- Inline query execution mixed with formatting
- No code reuse between dashboard and standalone insight contexts
- Duplicated error tracking query logic across `read_data` tool and `max_tools`
- Difficult to test components in isolation

The new context classes (`InsightContext`, `DashboardContext`, `ErrorTrackingFiltersContext`, `ErrorTrackingIssueContext`):
- Encapsulate query execution and formatting
- Are independently testable
- Can be reused across read_data tool, max_tools, and UI context
- Provide consistent patterns for all data types

## Test plan

1. **Manual testing**:
   - Ask Max "show me active errors in the last 7 days"
   - Verify the filter artifact appears and matches UI results
   - Ask Max to explain an error tracking issue
   - Verify the explain tool fetches stacktrace and provides analysis

2. **Automated tests**:
   - `pytest ee/hogai/artifacts/test/test_manager.py -v` (21 tests)
   - `pytest ee/hogai/context/dashboard/test/test_context.py -v` (11 tests)
   - `pytest ee/hogai/context/insight/test/test_context.py -v` (21 tests)
   - `pytest ee/hogai/context/error_tracking/test/test_context.py -v` (12 tests)
   - `pytest ee/hogai/tools/read_data/test/test_tool.py -v` (23 tests)
   - `pytest products/error_tracking/backend/test/test_max_tools.py -v` (22 tests)

3. **Regression testing**:
   - Verify existing insight/dashboard context still works
   - Verify Max can still read saved insights

## Screenshots

_Add screenshots of error tracking artifacts in Max chat_

## Checklist

- [x] Backend changes tested locally
- [x] Frontend changes tested locally
- [x] New types added to schema
- [x] Unit tests added for context classes (insight, dashboard, error_tracking)
- [x] Unit tests for error tracking max tools helper methods
- [x] Fixed artifact type validation in `aget_conversation_artifact_messages`
- [x] Updated `_read_artifacts` to format all artifact types
- [ ] E2E test for error tracking Max flow
