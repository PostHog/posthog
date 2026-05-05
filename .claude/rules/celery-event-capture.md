---
paths:
  - '**/tasks.py'
  - '**/tasks/**/*.py'
  - 'posthog/celery.py'
  - 'posthog/ph_client.py'
---

# PostHog event capture in Celery tasks

Do not use `posthoganalytics.capture()` in Celery tasks — events are silently lost.

Use `ph_scoped_capture` from `posthog.ph_client` instead (see its docstring for why and usage).
