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
- Task Worker: [Celery](https://docs.celeryproject.org/)

### Testing

- Frontend E2E tests: [Cypress](https://www.cypress.io/)
- Backend tests: [Pytest](https://docs.pytest.org/en/stable/getting-started.html) and [Django's built-in test suite](https://docs.djangoproject.com/en/3.1/topics/testing/)

### Additional tools

- CI/CD: [GitHub Actions](https://github.com/features/actions)
- Containerization: [Docker](https://www.docker.com/) and [Docker Compose](https://docs.docker.com/compose/)
- Linter (frontend): [ESLint](https://eslint.org/)
- Formatter (backend): [Black](https://pypi.org/project/black/)
