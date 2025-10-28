---
title: Backend coding conventions
sidebar: Handbook
---

#### Logging
As a general rule, we should have logs for every expected and unexpected actions of the application, using the appropriate _log level_.

We should also be logging these exceptions to Posthog. Python exceptions should almost always be captured automatically without extra instrumentation, but custom ones (such as failed requests to external services, query errors, or Celery task failures) can be tracked using `capture_exception()`.

##### Levels
A _log level_ or _log severity_ is a piece of information telling how important a given log message is:

* `DEBUG`: should be used for information that may be needed for diagnosing issues and troubleshooting or when running application
in the test environment for the purpose of making sure everything is running correctly
* `INFO`: should be used as standard log level, indicating that something happened
* `WARN`: should be used when something unexpected happened but the code can continue the work
* `ERROR`: should be used when the application hits an issue preventing one or more functionalities from properly functioning

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
As you can see above, the log contains all the information needed to understand the app behaviour.

##### Security
Don’t log sensitive information. Make sure you never log:

* authorization tokens
* passwords
* financial data
* health data
* PII (Personal Identifiable Information)

### Testing

* All new packages and most new significant functionality should come with unit tests
* Significant features should come with integration and/or end-to-end tests
* Analytics-related queries should be covered by snapshot tests for ease of reviewing
* For pytest use the `assert x == y` instead of the `self.assertEqual(x, y)` format of tests
    * it's recommended in the pytest docs
    * and you get better output when the test fails
* prefer assertions like `assert ['x', 'y'] == response.json()["results"]` over `assert len(response.json()["results"]) == 2`
    * that's because you want test output to give you the information you need to fix a failure
    * and because you want your assertions to be as concrete as possible it shouldn't be possible to break the code and the test pass

#### Fast developer ("unit") tests

A good test should:

* focus on a single use-case at a time
* have a minimal set of assertions per test
* explain itself well
* help you understand the system
* make good use of parameterized testing to show behavior with a range of inputs
* help us have confidence that the impossible is unrepresentable
* help us have confidence that the system will work as expected

#### Integration tests

* Integration tests should ensure that the feature works in the running system
* They give greater confidence (because you avoid the mistake of just testing a mock) but they're slower
* They are generally less brittle in response to changes because they test at a higher level than developer tests (e.g. they test a Django API not a class used inside it)

### To ee or not to ee?

We default to open but when adding a new feature we should consider if it should be MIT licensed or Enterprise edition licensed. Everything in the `ee` folder is covered by [a different license](https://github.com/PostHog/posthog/blob/master/ee/LICENSE). It's easy to move things from `ee` to open, but not the other way.

All the open source code is copied to [the posthog-foss repo](https://github.com/posthog/posthog-foss) with the `ee` code stripped out.  You need to consider whether your code will work if imports to `ee` are unavailable
