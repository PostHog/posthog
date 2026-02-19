---
title: Tech stack
sidebar: Docs
showTitle: true
---

> **Note:** This page refers to our [main product repository](https://github.com/PostHog/posthog), not our website.

### Frontend

- Web framework/library: [React](https://reactjs.org/)
- State management: [Redux](https://redux.js.org/) + [Kea](https://github.com/keajs/kea)
- Layout/components: [Ant Design](https://ant.design/)

### Backend

- Framework: [Django](https://www.djangoproject.com/)
- High scale services: [Rust](https://www.rust-lang.org/)
- Databases: [PostgreSQL](https://www.postgresql.org/) and [ClickHouse](https://clickhouse.tech/)
- Task queue/event streaming: [Redis](https://redis.io/) and [Apache Kafka](https://kafka.apache.org/)
- Task Worker: [Celery](https://docs.celeryproject.org/), [Temporal](https://temporal.io/) and [Dagster](https://dagster.io/)

### Testing

- Frontend E2E tests: [Playwright](https://playwright.dev/)
- Backend tests: [Pytest](https://docs.pytest.org/en/stable/getting-started.html) and [Django's built-in test suite](https://docs.djangoproject.com/en/3.1/topics/testing/)

### Additional tools

- CI/CD: [GitHub Actions](https://github.com/features/actions)
- Containerization: [Docker](https://www.docker.com/) and [Docker Compose](https://docs.docker.com/compose/)
- Linter (frontend): [ESLint](https://eslint.org/)
- Formatter (backend): [Black](https://pypi.org/project/black/)

### Workflow orchestration

We historically used Celery as our task worker. At PostHog’s current scale Celery can be unreliable for larger or long-running workflows, but it remains a practical fit for **small, low-latency background tasks** (e.g. sending emails or other quick async side-effects). New medium- and large-scale jobs should use Temporal or Dagster instead.

We use both **[Temporal](https://temporal.io/)** and **[Dagster](https://dagster.io/)** for more complex orchestration, each chosen for their specific strengths.

#### When to use each tool

We tend to use **Celery for lightweight ad-hoc tasks**, **Dagster for internal data jobs**, and **Temporal for user-facing workflows**. You can look at the problem from the requirements for your jobs:

1. **Is it a tiny, low-latency, fire-and-forget task (e.g. send email)?** → Celery
2. **Is it mission-critical with complex failure scenarios?** → Temporal
3. **Do you need exactly-once guarantees?** → Temporal
4. **Do you need complex retry policies or long-running workflows?** → Temporal
5. **Is it primarily about scheduled data transformation?** → Dagster
6. **Do you need rich data lineage and testing?** → Dagster

#### Where do we use each?

These are examples of where we use Temporal and Dagster at PostHog. Hopefully, these can serve as anecdotal examples to help you pick between Temporal and Dagster for your application. This list is not exhaustive.

**Celery**: Small, fast background tasks (e.g. sending email, minor async operations)
**Temporal**: Batch exports, data warehouse source syncing, AI platform task generation
**Dagster**: Exchange rate tracking, one-off production management commands (better monitoring than Django's management commands), web analytics data pre-processing
