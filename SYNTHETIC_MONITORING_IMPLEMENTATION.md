# Synthetic Monitoring MVP - Implementation Summary

## Overview

This PR implements the MVP for PostHog Synthetic Monitoring with AWS Lambda execution. Users can monitor HTTP endpoint uptime and latency from multiple AWS regions, with all results stored as events in ClickHouse for unified analytics and alerting.

## Architecture

**ClickHouse-Only Event Pattern:**

- Monitor configurations stored in PostgreSQL (Django model)
- **All check results stored as events in ClickHouse** - no state tracking in Postgres
- Monitor state (last_checked_at, consecutive_failures, state) computed from ClickHouse events on-demand
- Only `last_alerted_at` stored in Postgres (alert cooldown state)
- AWS Lambda functions deployed per region for true multi-region monitoring
- External service sends results to PostHog via webhook/API, which stores them as events

## What's Implemented (Backend Complete)

### 1. Data Models (`posthog/models/synthetic_monitor.py`)

- `SyntheticMonitor`: Main model for monitor configuration
  - **HTTP checks only** (web performance removed for MVP)
  - Configurable frequency (1-60 minutes)
  - Multi-region support via `regions` field (list of AWS regions)
  - Integrated alert configuration (email + Slack)
  - **All check results stored in ClickHouse** - monitor state (last_checked_at, consecutive_failures, state) is computed from ClickHouse events on-demand
  - Only `last_alerted_at` stored in Postgres (alert state, not check result state)

### 2. Database Migration (`posthog/migrations/0901_synthetic_monitoring.py`)

- Creates `SyntheticMonitor` table only
- Indexes for performance: `(team, enabled)`
- No check table (results stored as events)

### 3. AWS Lambda Function (`lambda/synthetic-monitor/`)

TODO. Do not implement this for now.

### 4. REST API (`posthog/api/synthetic_monitor.py`)

**Endpoints:**

- `GET /api/projects/:id/synthetic_monitors/` - List monitors
- `POST /api/projects/:id/synthetic_monitors/` - Create monitor
- `GET /api/projects/:id/synthetic_monitors/:monitor_id/` - Get monitor details
- `PUT/PATCH /api/projects/:id/synthetic_monitors/:monitor_id/` - Update monitor (use `enabled` field to pause/resume)
- `DELETE /api/projects/:id/synthetic_monitors/:monitor_id/` - Delete monitor
- `POST /api/projects/:id/synthetic_monitors/:monitor_id/test/` - Trigger test check

**Features:**

- Search and filtering by enabled status (state filtering requires ClickHouse queries)
- Full CRUD operations with validation
- User action tracking for analytics
- Check history and monitor state computed from ClickHouse events on-demand

### 5. Execution and Alerts

**External Service Execution:**

- Check execution is handled by an external AWS Lambda service
- The external service runs on a fixed cron schedule
- Results are sent back to PostHog via webhook or API

**Alert Handling:**

- Alerts are triggered when monitors fail (handled by external service or webhook)
  - 1-hour cooldown between alerts
  - Email notifications to configured recipients
  - Slack notifications via Integration model
  - Configurable failure threshold

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

1. **AWS Lambda** runs on a fixed cron schedule (external to PostHog)
2. **Lambda executes** HTTP check using Python `urllib`
3. **Lambda sends results** to PostHog via webhook/API endpoint
4. **PostHog webhook handler** stores result as `synthetic_http_check` event in ClickHouse
5. **Alert logic** (in webhook handler) queries ClickHouse to determine if alerts should be triggered

### Webhook Endpoint

The external Lambda service sends check results to PostHog via webhook:

- `POST /api/projects/:id/synthetic_monitors/webhook/`
- Receives check result payload and stores as ClickHouse event
- Computes alert state from ClickHouse events if needed

### Deployment

See `lambda/synthetic-monitor/README.md` for Lambda deployment instructions.

## Alert Flow

1. External service executes check and sends result to PostHog via webhook/API
2. PostHog stores result as `synthetic_http_check` event in ClickHouse
3. Alert logic (in webhook handler or external service) queries ClickHouse to compute consecutive failures
4. When consecutive failures (from ClickHouse events) >= `alert_threshold_failures`:
   - Alert triggered (if not in cooldown - checked via `last_alerted_at` in Postgres)
   - Email sent to `alert_recipients`
   - Slack message sent to `slack_integration`
   - `last_alerted_at` updated in Postgres

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
