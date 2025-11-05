# Synthetic Monitoring MVP - Implementation Summary

## Overview
This PR implements the MVP for PostHog Synthetic Monitoring, allowing users to monitor uptime, latency, and web performance directly within PostHog, with all results stored as events for unified analytics and alerting.

## What's Implemented (Backend Complete)

### 1. Data Models (`posthog/models/synthetic_monitor.py`)
- `SyntheticMonitor`: Main model for monitor configuration
  - Supports HTTP checks and Web Performance checks
  - Configurable frequency (1-60 minutes)
  - Regional monitoring support (multi-region ready)
  - Integrated alert configuration
  - State management (healthy, failing, error, disabled)

- `SyntheticMonitorCheck`: Historical check records
  - HTTP check results (response time, status code, errors)
  - Web Performance metrics (Lighthouse scores, Core Web Vitals)
  - Per-region tracking

### 2. Database Migration (`posthog/migrations/0901_synthetic_monitoring.py`)
- Creates `SyntheticMonitor` and `SyntheticMonitorCheck` tables
- Proper indexes for performance
- Foreign key constraints

### 3. REST API (`posthog/api/synthetic_monitor.py`)
**Endpoints:**
- `GET /api/projects/:id/synthetic_monitors/` - List monitors
- `POST /api/projects/:id/synthetic_monitors/` - Create monitor
- `GET /api/projects/:id/synthetic_monitors/:monitor_id/` - Get monitor details
- `PUT/PATCH /api/projects/:id/synthetic_monitors/:monitor_id/` - Update monitor
- `DELETE /api/projects/:id/synthetic_monitors/:monitor_id/` - Delete monitor
- `POST /api/projects/:id/synthetic_monitors/:monitor_id/test/` - Trigger test check
- `POST /api/projects/:id/synthetic_monitors/:monitor_id/pause/` - Pause monitoring
- `POST /api/projects/:id/synthetic_monitors/:monitor_id/resume/` - Resume monitoring
- `GET /api/projects/:id/synthetic_monitors/:monitor_id/checks/` - Get check history

**Features:**
- Search and filtering by state, type, enabled status
- Recent checks included in monitor details
- Full CRUD operations with validation
- User action tracking for analytics

### 4. Webhook Endpoint (`posthog/api/synthetic_monitor_webhook.py`)
- `POST /api/synthetic_monitor_webhook` - Receives check results from external service
- Validates payload and creates check records
- Updates monitor state (success/failure tracking)
- Emits PostHog events (`synthetic_http_check`, `synthetic_web_score`)
- Triggers alerts when thresholds are exceeded

### 5. Celery Tasks (`posthog/tasks/alerts/synthetic_monitoring.py`)
**Scheduled Tasks:**
- `schedule_synthetic_checks()` - Runs every minute to trigger due checks
- `cleanup_old_synthetic_checks()` - Daily cleanup of old check records (30-day retention)

**Background Tasks:**
- `trigger_external_check()` - Calls external service API to execute checks
- `send_synthetic_monitor_alert()` - Sends email and Slack notifications

**Alert Features:**
- Email notifications to configured recipients
- Slack integration support
- Alert cooldown (max once per hour)
- Configurable failure threshold

### 6. Email Template (`posthog/templates/email/synthetic_monitor_alert.html`)
- Professional alert email design
- Monitor details and failure information
- Direct link to monitor dashboard
- Error details and diagnostics

### 7. Periodic Task Setup (`posthog/tasks/scheduled.py`)
- Integrated with PostHog's Celery scheduler
- Checks run every minute
- Automatic cleanup daily at 2 AM

## Event Schema

### HTTP Check Event (`synthetic_http_check`)
```json
{
  "event": "synthetic_http_check",
  "distinct_id": "monitor_<uuid>",
  "properties": {
    "monitor_id": "uuid",
    "monitor_name": "My Monitor",
    "monitor_type": "http",
    "url": "https://example.com",
    "region": "us-east-1",
    "success": true,
    "response_time_ms": 150,
    "status_code": 200,
    "error_message": null
  }
}
```

### Web Performance Event (`synthetic_web_score`)
```json
{
  "event": "synthetic_web_score",
  "distinct_id": "monitor_<uuid>",
  "properties": {
    "monitor_id": "uuid",
    "monitor_name": "My Monitor",
    "monitor_type": "web_performance",
    "url": "https://example.com",
    "region": "us-east-1",
    "success": true,
    "performance_score": 95,
    "accessibility_score": 100,
    "best_practices_score": 92,
    "seo_score": 90,
    "lcp": 1200.5,
    "inp": 50.2,
    "cls": 0.05,
    "fcp": 800.3,
    "ttfb": 100.1
  }
}
```

## External Service Integration

The system is designed to work with an external Lambda/Cloudflare Workers service:

1. **PostHog triggers check** via `trigger_external_check()` task
2. **External service executes** HTTP/web performance check
3. **Results posted back** to `/api/synthetic_monitor_webhook`
4. **PostHog processes** results, updates state, emits events, triggers alerts

### Configuration Required
```python
# settings.py
SYNTHETIC_MONITORING_EXTERNAL_SERVICE_URL = "https://your-service.com/check"
SYNTHETIC_MONITORING_API_KEY = "your-api-key"
```

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
