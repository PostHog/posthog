---
title: Backend coding conventions
sidebar: Handbook
---

#### Logging

As a general rule, we should have logs for every expected and unexpected actions of the application, using the appropriate _log level_.

We should also be logging these exceptions to Posthog. Python exceptions should almost always be captured automatically without extra instrumentation, but custom ones (such as failed requests to external services, query errors, or Celery task failures) can be tracked using `capture_exception()`.

##### Levels

A _log level_ or _log severity_ is a piece of information telling how important a given log message is:

- `DEBUG`: should be used for information that may be needed for diagnosing issues and troubleshooting or when running application
  in the test environment for the purpose of making sure everything is running correctly
- `INFO`: should be used as standard log level, indicating that something happened
- `WARN`: should be used when something unexpected happened but the code can continue the work
- `ERROR`: should be used when the application hits an issue preventing one or more functionalities from properly functioning

##### Format

`django-structlog` is the default logging library we use (see [docs](https://django-structlog.readthedocs.io/en/latest/)).
It's a _structured logging_ framework that adds cohesive metadata on each logs that makes it easier to track events or incidents.

Structured logging means that you don’t write hard-to-parse and hard-to-keep-consistent prose in your logs
but that you log events that happen in a context instead.

```python
import structlog
logger = structlog.get_logger(__name__)
logger.debug("event_sent_to_kafka", event_uuid=str(event_uuid), kafka_topic=topic)
```

will produce:

```console
2021-10-28T13:46:40.099007Z [debug] event_sent_to_kafka [posthog.api.capture] event_uuid=017cc727-1662-0000-630c-d35f6a29bae3 kafka_topic=default
```

As you can see above, the log contains all the information needed to understand the app behavior.

##### Enabling INFO logs for your module

By default, most `posthog.*` loggers only output WARNING and above. This keeps production logs clean but means your `logger.info()` calls won't appear.

To enable INFO logging for a specific module, add it to `posthog/settings/logs.py`:

```python
"loggers": {
    # ... existing loggers ...
    "posthog.tasks.my_module": {"level": "INFO", "handlers": ["console"], "propagate": False},
}
```

Note: calling `logger.setLevel(logging.INFO)` in your code doesn't work with structlog - you must add the config entry above.

Celery task lifecycle events (`task_started`, `task_succeeded`, etc.) are logged automatically by `django-structlog` at INFO level and are already enabled.

##### Security

Don’t log sensitive information. Make sure you never log:

- authorization tokens
- passwords
- financial data
- health data
- PII (Personal Identifiable Information)

### Testing

A test suite is a shared, permanent liability: every test runs on every PR forever, costs CI time, can flake and block unrelated work, and is code someone has to maintain as the system changes.
So judge a new test on two independent axes — **value** (does it catch a realistic regression we actually make?) and **cost** (how far down the test pyramid does it sit?).
Maximize value and minimize cost; this never means "write fewer tests", it means drop the ones that catch nothing and push the rest as far down the pyramid as they go.

- All new packages and most new significant functionality should come with unit tests
- Significant features should come with integration and/or end-to-end tests
- Analytics-related queries should be covered by snapshot tests for ease of reviewing
- For pytest use the `assert x == y` instead of the `self.assertEqual(x, y)` format of tests
  - it's recommended in the pytest docs
  - and you get better output when the test fails
- prefer assertions like `assert ['x', 'y'] == response.json()["results"]` over `assert len(response.json()["results"]) == 2`
  - that's because you want test output to give you the information you need to fix a failure
  - and because you want your assertions to be as concrete as possible it shouldn't be possible to break the code and the test pass

#### Does this test earn its place?

Before writing a test, answer in one sentence: **what realistic regression does this catch that no existing test already catches?**
Name the bug, the code path, and the input that would break — "increases coverage", "good practice", and "the function exists" are not answers.
A good answer sounds like _"if someone makes `parse_filters` drop the `team_id` clause, this fails"_.

Most low-value tests are one of these — recognize them and extend an existing test (or delete the code) instead:

- **Trivial / framework behavior**: getters, setters, constants, that Django saved a row or that DRF serialized a field. You're testing someone else's code, not yours.
- **Change-detector tests**: asserting which private methods were called, with mocks wired to match the current code. They fail on every refactor and catch no real bug. Assert observable behavior through the public interface (return value, persisted state, emitted event, HTTP response), not the choreography that produces it. See [Change-Detector Tests Considered Harmful](https://testing.googleblog.com/2015/01/testing-on-toilet-change-detector-tests.html).
- **Redundant coverage**: a new test that's a variation of an existing one is a `@parameterized` case (Python) or a `test.each` row (Jest), not a new test function.
- **Coverage-chasing**: an uncovered line is information, not a defect — don't add a test just to move the number.

#### Weight tests down the pyramid

Each rung is roughly an order of magnitude slower and flakier than the one below:

```text
pure function  →  kea logic test  →  Django TestCase  →  ClickHouse-backed test  →  Playwright e2e
   cheapest                                                                          most expensive
```

Aim for a ratio, not a cap: many tests at the bottom, very few at the top — if you want more coverage, add it at the bottom.
When logic is hard to test cheaply, that's a design signal: extract it into a pure function (or a kea logic) and test that directly rather than standing up a database, a request, and a render.
Escalating to the next rung is the last resort, not the default.

- **Use `TestCase`, not `TransactionTestCase`, unless you truly need it.** `TransactionTestCase` flushes the DB between tests instead of rolling back a transaction — dramatically slower, and a common source of cross-test interference. For `transaction.on_commit` side effects use `self.captureOnCommitCallbacks(execute=True)`; reaching ClickHouse is not a reason to switch (`ClickhouseTestMixin` runs on a plain `TestCase`).
- Mock only true boundaries — network, external APIs, the clock, queues. Don't mock your own internal helpers; that's how change-detector tests are born.
- Frontend: prefer a kea logic test (`logic.actions` / `logic.values`) over a full component render whenever the behavior lives in the logic, and don't snapshot large rendered trees — assert specific fields instead.
- Keep tests deterministic and isolated: no `time.sleep` or arbitrary waits (use `freeze_time` or wait on a real condition), no real network or live external services, and they must pass in any order. Don't leave a `@skip`/`xfail`/`.only` without a one-line reason and a linked issue.

#### Fast developer ("unit") tests

A good test should:

- focus on a single use-case at a time
- have a minimal set of assertions per test
- explain itself well
- help you understand the system
- make good use of parameterized testing to show behavior with a range of inputs
- help us have confidence that the impossible is unrepresentable
- help us have confidence that the system will work as expected

#### Integration tests

- Integration tests should ensure that the feature works in the running system
- They give greater confidence (because you avoid the mistake of just testing a mock) but they're slower
- They are generally less brittle in response to changes because they test at a higher level than developer tests (e.g. they test a Django API not a class used inside it)

### Querying ClickHouse

**Always use HogQL instead of raw ClickHouse queries in product code.**

Querying ClickHouse directly from product code is a bad idea for several reasons:

1. **Data safety**: HogQL automatically scopes queries to the current team, preventing accidental cross-team data access. Raw queries that fetch data for multiple teams and separate it in code are risky—even if correct now, future changes could introduce data breaches.

2. **Consistency**: HogQL handles property access, person mapping, and other PostHog-specific concerns correctly and consistently.

3. **Query attribution**: If you must query ClickHouse directly for a valid reason, ensure you [tag your queries appropriately](https://posthog.com/handbook/engineering/clickhouse/query-attribution) with the right product tag and ClickHouse user.

The only case where raw ClickHouse queries might be justified is cross-team queries, but even then consider alternatives:

- Can you detect what you need via PostgreSQL instead? (e.g., checking feature usage via team settings)
- Can you use one simple ClickHouse query to get team IDs, then run HogQL queries per-team for the actual data?
- Can you leverage existing cross-team infrastructure like usage reports?

### To ee or not to ee?

We default to open but when adding a new feature we should consider if it should be MIT licensed or Enterprise edition licensed. Everything in the `ee` folder is covered by [a different license](https://github.com/PostHog/posthog/blob/master/ee/LICENSE). It's easy to move things from `ee` to open, but not the other way.

All the open source code is copied to [the posthog-foss repo](https://github.com/posthog/posthog-foss) with the `ee` code stripped out. You need to consider whether your code will work if imports to `ee` are unavailable.

> Sync note: This file is also copied to posthog/posthog/.claude/commands/conventions.md for Claude Code. When updating this file, please also update the copy there.
