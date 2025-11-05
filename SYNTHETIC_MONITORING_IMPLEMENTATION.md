# Synthetic Monitoring MVP - Implementation Summary

## Overview

This PR implements the MVP for PostHog Synthetic Monitoring with AWS Lambda execution. Users can monitor HTTP endpoint uptime and latency from multiple AWS regions, with all results stored as events in ClickHouse for unified analytics and alerting.

## Architecture

**Simplified Event-Only Pattern:**

- Monitor configurations stored in PostgreSQL (Django model)
- Check results stored as events in ClickHouse (no separate check table)
- AWS Lambda functions deployed per region for true multi-region monitoring
- Celery tasks invoke Lambda and wait for results (15s timeout)

## What's Implemented (Backend Complete)

### 1. Data Models (`posthog/models/synthetic_monitor.py`)

- `SyntheticMonitor`: Main model for monitor configuration
  - **HTTP checks only** (web performance removed for MVP)
  - Configurable frequency (1-60 minutes)
  - Multi-region support via `regions` field (list of AWS regions)
  - Integrated alert configuration (email + Slack)
  - State management (healthy, failing, error, disabled)
  - No CheckConstraint for Django compatibility

### 2. Database Migration (`posthog/migrations/0901_synthetic_monitoring.py`)

- Creates `SyntheticMonitor` table only
- Indexes for performance: `(team, enabled)`, `(next_check_at)`
- No check table (results stored as events)

### 3. AWS Lambda Function (`lambda/synthetic-monitor/`)

TODO. Do not implement this for now.

### 4. REST API (`posthog/api/synthetic_monitor.py`)

**Endpoints:**

- `GET /api/projects/:id/synthetic_monitors/` - List monitors
- `POST /api/projects/:id/synthetic_monitors/` - Create monitor
- `GET /api/projects/:id/synthetic_monitors/:monitor_id/` - Get monitor details
- `PUT/PATCH /api/projects/:id/synthetic_monitors/:monitor_id/` - Update monitor
- `DELETE /api/projects/:id/synthetic_monitors/:monitor_id/` - Delete monitor
- `POST /api/projects/:id/synthetic_monitors/:monitor_id/test/` - Trigger test check
- `POST /api/projects/:id/synthetic_monitors/:monitor_id/pause/` - Pause monitoring
- `POST /api/projects/:id/synthetic_monitors/:monitor_id/resume/` - Resume monitoring

**Features:**

- Search and filtering by state, enabled status
- Full CRUD operations with validation
- User action tracking for analytics
- Check history queried from events (not included in API response)

### 5. Celery Tasks (`posthog/tasks/alerts/synthetic_monitoring.py`)

**Scheduled Tasks:**

- `schedule_synthetic_checks()` - Runs every minute to trigger due checks
  - Spawns `execute_http_check` task for each monitor × region combination

**Execution Tasks:**

- `execute_http_check(monitor_id, region)` - Invokes AWS Lambda synchronously
  - Creates boto3 Lambda client for specified region
  - Invocation type: RequestResponse (waits for result)
  - 15-second timeout for Lambda response
  - Parses Lambda response payload
  - Updates monitor state (success/failure tracking)
  - Emits `synthetic_http_check` event to ClickHouse
  - Triggers alert task if threshold exceeded

**Alert Tasks:**

- `send_synthetic_monitor_alert()` - Sends notifications when monitors fail
  - 1-hour cooldown between alerts
  - Email notifications to configured recipients
  - Slack notifications via Integration model
  - Configurable failure threshold

### 6. Periodic Task Setup (`posthog/tasks/scheduled.py`)

- Integrated with PostHog's Celery scheduler
- `schedule_synthetic_checks` runs every 60 seconds

## Event Schema

### HTTP Check Event (`synthetic_http_check`)

All check results are stored as events in ClickHouse:

```json
{
  "event": "synthetic_http_check",
  "distinct_id": "monitor_<uuid>",
  "properties": {
    "monitor_id": "uuid",
    "monitor_name": "My Monitor",
    "url": "https://example.com",
    "method": "GET",
    "region": "us-east-1",
    "success": true,
    "status_code": 200,
    "response_time_ms": 150,
    "error_message": null,
    "expected_status_code": 200,
    "consecutive_failures": 0
  }
}
```

## AWS Lambda Integration

### Architecture

1. **PostHog Celery task** invokes AWS Lambda function in specified region
2. **Lambda executes** HTTP check using Python `urllib`
3. **Lambda returns** results synchronously (15s timeout)
4. **PostHog processes** results, updates state, emits events, triggers alerts

### Required Configuration

```python
# settings.py or environment variables
SYNTHETIC_MONITOR_LAMBDA_FUNCTION_NAME = "posthog-synthetic-monitor"  # default
AWS_ACCESS_KEY_ID = "your-access-key"  # IAM user with lambda:InvokeFunction
AWS_SECRET_ACCESS_KEY = "your-secret-key"
```

### Deployment

See `lambda/synthetic-monitor/README.md` and `lambda/synthetic-monitor/SETTINGS.md` for detailed instructions.

## Alert Flow

1. Check fails → `consecutive_failures` increments
2. When `consecutive_failures >= alert_threshold_failures`:
   - Alert triggered (if not in cooldown)
   - Email sent to `alert_recipients`
   - Slack message sent to `slack_integration`
   - `last_alerted_at` updated
3. Check succeeds → `consecutive_failures` resets to 0

## What's Next (Frontend + Tests)

### Frontend Implementation Needed:

1. **Scene structure** (`frontend/src/scenes/synthetic-monitoring/`)
   - Monitor list view with status indicators
   - Create/edit monitor form
   - Monitor detail page with check history
   - Dashboard widgets for aggregated stats

2. **Navigation**
   - Add menu item in main navigation
   - Link to synthetic monitoring scene

3. **Components**
   - Status badges (healthy/failing/error)
   - Check history table/chart
   - Alert configuration UI
   - Region selector

### Testing Needed:

1. **Backend Tests** (`posthog/models/test/`)
   - Model validation tests
   - API endpoint tests
   - Webhook endpoint tests
   - Celery task tests
   - Alert logic tests

2. **Frontend Tests** (Jest)
   - Component rendering tests
   - Form validation tests
   - API integration tests

## Files Modified/Created

### Created:

- `posthog/models/synthetic_monitor.py`
- `posthog/migrations/0901_synthetic_monitoring.py`
- `posthog/api/synthetic_monitor.py`
- `posthog/api/synthetic_monitor_webhook.py`
- `posthog/tasks/alerts/synthetic_monitoring.py`
- `posthog/templates/email/synthetic_monitor_alert.html`

### Modified:

- `posthog/models/__init__.py` - Added model exports
- `posthog/api/__init__.py` - Registered API viewset
- `posthog/urls.py` - Added webhook endpoint
- `posthog/tasks/scheduled.py` - Added periodic tasks

## Architecture Decisions

1. **External Service Pattern**: Chose external Lambda/Workers for execution to support multi-region checks without deploying PostHog globally

2. **Integrated Alerts**: Embedded alert config in `SyntheticMonitor` model for simplicity (vs separate `AlertConfiguration` records)

3. **Event-Based**: All check results stored as PostHog events for unified analytics

4. **Hybrid Performance Checks**: Start with PSI API (rate limited but simple), plan migration to local Lighthouse for scale

5. **Webhook Pattern**: External service POSTs results back, enabling async/multi-region execution

## Next Steps

1. Implement frontend UI (scenes, components, navigation)
2. Write comprehensive tests (pytest + Jest)
3. Create external service (Lambda/Workers) for check execution
4. Add dashboard templates for monitoring overview
5. Documentation (user guide, API docs, setup instructions)
6. Performance optimization and monitoring
