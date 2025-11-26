# Alerts Module

Background tasks for evaluating PostHog alerts.

## Overview

This module handles the periodic evaluation of alerts configured on insights. When an alert condition is met, notifications are sent to subscribed users.

## Alert Types

### Threshold Alerts (checks.py, trends.py)

Traditional alerts that fire when a metric crosses a defined threshold:

- Absolute value thresholds (above/below)
- Percentage increase/decrease thresholds
- Support for single series or aggregated values

### Forecast Alerts (forecast.py)

Anomaly detection using probabilistic forecasting:

- Uses Chronos-Bolt model to predict expected value ranges
- Fires when actual value falls outside the confidence interval
- Supports configurable confidence levels (e.g., 95%, 99%)

See `posthog/temporal/forecast/README.md` for forecast implementation details.

## Components

### checks.py

Main entry point for alert evaluation:

- `check_alert()` - Evaluates a single alert
- Dispatches to appropriate handler based on alert type
- Manages alert state transitions (firing, not firing, errored)

### trends.py

Evaluation logic for trends-based alerts:

- Queries insight data for current values
- Compares against configured thresholds
- Handles breakdowns and multiple series

### forecast.py

Forecast alert evaluation:

- `check_forecast_alert()` - Single series forecast check
- `check_forecast_alert_multi_series()` - Multiple series/breakdowns
- Triggers on-demand forecast generation via Temporal if needed

### utils.py

Shared utilities:

- `AlertEvaluationResult` - Standard result format
- Date range helpers
- Notification logic

### constants.py

Feature flags and configuration constants.

## Alert Lifecycle

```text
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│  Scheduled   │────>│  Evaluate    │────>│   Notify     │
│  (Celery)    │     │  Condition   │     │   Users      │
└──────────────┘     └──────────────┘     └──────────────┘
                            │
                            v
                     ┌──────────────┐
                     │ Update State │
                     │ AlertCheck   │
                     └──────────────┘
```

## Configuration

Alerts are configured via `AlertConfiguration` model with:

- `calculation_interval` - How often to check (hourly, daily, weekly, monthly)
- `condition` - Alert condition type and parameters
- `threshold` - Threshold configuration (for threshold alerts)
- `config` - Type-specific config (e.g., `ForecastAlertConfig`)

## Testing

```bash
pytest posthog/tasks/alerts/test/
```
