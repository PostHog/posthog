# Forecast Module

Time series forecasting using the Chronos-Bolt model for predictive alerting.

## Overview

This module provides probabilistic forecasting capabilities for PostHog alerts. It uses Amazon's Chronos-Bolt model to generate prediction intervals that can be used to detect anomalies (values outside expected bounds).

## Architecture

```text
┌─────────────────────┐     ┌──────────────────────┐     ┌─────────────────────┐
│  Alert Check Task   │────>│  Temporal Workflow   │────>│  Chronos Service    │
│  (forecast.py)      │     │  (workflows.py)      │     │  (chronos_service)  │
└─────────────────────┘     └──────────────────────┘     └─────────────────────┘
                                      │
                                      v
                            ┌──────────────────────┐
                            │   ForecastResult     │
                            │   (PostgreSQL)       │
                            └──────────────────────┘
```

## Components

### chronos_service.py

Wrapper around the Chronos-Bolt model. Provides:

- `forecast()` - Single series prediction with confidence intervals
- `forecast_batch()` - Batch prediction for multiple series
- Lazy model loading to avoid memory overhead at worker startup

### workflows.py

Temporal workflow (`forecast-generation`) that orchestrates:

1. Fetching historical data from the insight
2. Running the Chronos model to generate forecasts
3. Storing results in PostgreSQL

### activities.py

Temporal activities:

- `fetch_historical_data_activity` - Queries insight data
- `generate_forecast_activity` - Runs Chronos model
- `store_forecast_result_activity` - Persists forecasts to DB

### inputs.py

Dataclasses for workflow/activity inputs and outputs.

## Usage

Forecasts are generated on-demand when a forecast alert is checked and no recent forecast exists. The workflow runs on Temporal workers with the `FORECAST_INFERENCE_TASK_QUEUE`.

### Backfilling Historical Forecasts

To backfill forecasts for visualization on charts:

```bash
python manage.py backfill_forecast_results --alert-id <uuid> [--max-forecasts 30]
```

This runs the Chronos model against historical data points to generate retrospective forecasts.

## Model Details

- Model: `amazon/chronos-bolt-tiny`
- Quantiles: Maps confidence level to available quantiles (0.1 to 0.9)
- Output: Predicted value, lower bound, upper bound for the forecast horizon

## Configuration

- `FORECAST_INFERENCE_TASK_QUEUE` - Temporal task queue for forecast workers
- `MIN_HISTORICAL_POINTS` - Minimum data points required (default: 10)

## Dependencies

Requires optional dependencies:

```bash
pip install 'posthog[forecast]'
```

This installs `chronos-forecasting` and `torch`.
