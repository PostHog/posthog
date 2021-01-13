# PostHog Plugin Server

[![npm package](https://img.shields.io/npm/v/posthog-plugin-server?style=flat-square)](https://www.npmjs.com/package/posthog-plugin-server)
[![MIT License](https://img.shields.io/badge/License-MIT-red.svg?style=flat-square)](https://opensource.org/licenses/MIT)

This service takes care of processing events with plugins and more.

## Get started

Let's get you developing the plugin server in no time:

1. Install dependencies and prepare for takeoff by running command `yarn`.

1. Start a development instance of [PostHog](/PostHog/posthog). After all, this is the _PostHog_ Plugin Server, and it works in conjuction with the main server. To avoid interference, disable the plugin server there.

1. Make sure that the plugin server is configured correctly (see [Configuration](#Configuration)). Two settings that you MUST get right are DATABASE_URL and REDIS_URL - they need to be identical between the plugin server and the main server.

1. If developing the enterprise Kafka + ClickHouse pipeline, set KAFKA_ENABLED to `true` and provide KAFKA_HOSTS.

    Otherwise if developing the basic Redis + Postgres pipeline, skip ahead.

1. Start the plugin server in autoreload mode with `yarn start`, or in compiled mode with `yarn build && yarn start:dist`, and develop away!

1. Run tests with `yarn test`. Run benchmarks with `yarn benchmark`.

## Configuration

There's a multitude of settings you can use to control the plugin server. Use them as environment variables.

| Name                          | Description                                                | Default value                         |
| ----------------------------- | ---------------------------------------------------------- | ------------------------------------- |
| DATABASE_URL                  | Postgres database URL                                      | `'postgres://localhost:5432/posthog'` |
| REDIS_URL                     | Redis store URL                                            | `'redis://localhost'`                 |
| BASE_DIR                      | base path for resolving local plugins                      | `'.'`                                 |
| WORKER_CONCURRENCY            | number of concurrent worker threads                        | `0` – all cores                       |
| TASKS_PER_WORKER              | number of parallel tasks per worker thread                 | `10`                                  |
| SCHEDULE_LOCK_TTL             | How many seconds to hold the lock for the schedule         | `60`                                  |
| CELERY_DEFAULT_QUEUE          | Celery outgoing queue                                      | `'celery'`                            |
| PLUGINS_CELERY_QUEUE          | Celery incoming queue                                      | `'posthog-plugins'`                   |
| PLUGINS_RELOAD_PUBSUB_CHANNEL | Redis channel for reload events                            | `'reload-plugins'`                    |
| KAFKA_ENABLED                 | use Kafka instead of Celery to ingest events               | `false`                               |
| KAFKA_HOSTS                   | comma-delimited Kafka hosts                                | `null`                                |
| KAFKA_CLIENT_CERT_B64         | Kafka certificate in Base64                                | `null`                                |
| KAFKA_CLIENT_CERT_KEY_B64     | Kafka certificate key in Base64                            | `null`                                |
| KAFKA_TRUSTED_CERT_B64        | Kafka trusted CA in Base64                                 | `null`                                |
| DISABLE_WEB                   | whether to disable web server                              | `true`                                |
| WEB_PORT                      | port for web server to listen on                           | `3008`                                |
| WEB_HOSTNAME                  | hostname for web server to listen on                       | `'0.0.0.0'`                           |
| LOG_LEVEL                     | minimum log level                                          | `LogLevel.Info`                       |
| SENTRY_DSN                    | Sentry ingestion URL                                       | `null`                                |
| STATSD_HOST                   | StatsD host - integration disabled if this is not provided | `null`                                |
| STATSD_PORT                   | StatsD port                                                | `8125`                                |
| STATSD_PREFIX                 | StatsD prefix                                              | `'plugin-server.'`                    |

## Questions?

### [Join our Slack community.](posthog.com/slack)
