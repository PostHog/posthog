# PostHog Plugin Server

[![npm package](https://img.shields.io/npm/v/@posthog/plugin-server?style=flat-square)](https://www.npmjs.com/package/@posthog/plugin-server)
[![MIT License](https://img.shields.io/badge/License-MIT-red.svg?style=flat-square)](https://opensource.org/licenses/MIT)

This service takes care of processing events with plugins and more.

## Get started

Let's get you developing the plugin server in no time:

1. Have virtual environment from the main PostHog repo active.

1. Install dependencies and prepare for takeoff by running command `yarn`.

1. Start a development instance of [PostHog](/PostHog/posthog) - [instructions here](https://posthog.com/docs/developing-locally). After all, this is the _PostHog_ Plugin Server, and it works in conjuction with the main server.

1. Make sure that the plugin server is configured correctly (see [Configuration](#Configuration)). The following settings need to be the same for the plugin server and the main server: `DATABASE_URL`, `REDIS_URL`, `KAFKA_HOSTS`, `CLICKHOUSE_HOST`, `CLICKHOUSE_DATABASE`, `CLICKHOUSE_USER`, and `CLICKHOUSE_PASSWORD`. Their default values should work just fine in local development though.

1. Start the plugin server in autoreload mode with `yarn start`, or in compiled mode with `yarn build && yarn start:dist`, and develop away!

1. Prepare for running tests with `yarn setup:test`, which will run the necessary migrations. Run the tests themselves with `yarn test:{1,2}`.

## CLI flags

There are also a few alternative utility options on how to boot plugin-server.
Each one does a single thing. They are listed in the table below, in order of precedence.

| Name        | Description                                                | CLI flags         |
| ----------- | ---------------------------------------------------------- | ----------------- |
| Help        | Show plugin server [configuration options](#configuration) | `-h`, `--help`    |
| Version     | Only show currently running plugin server version          | `-v`, `--version` |
| Healthcheck | Check plugin server health and exit with 0 or 1            | `--healthcheck`   |
| Migrate     | Migrate Graphile job queue                                 | `--migrate`       |

## Alternative modes

By default, plugin-server is responsible for and executes all of the following:

1. Ingestion (calling plugins and writing event and person data to ClickHouse and Postgres, buffering events)
2. Scheduled tasks (runEveryX type plugin tasks)
3. Processing plugin jobs
4. Async plugin tasks (onEvent, onSnapshot plugin tasks)

Ingestion can be split into its own process at higher scales. To do so, you need to run two different instances of
plugin-server, with the following environment variables set:

| Env Var                        | Description                                                                                                                     |
| ------------------------------ | ------------------------------------------------------------------------------------------------------------------------------- |
| `PLUGIN_SERVER_MODE=ingestion` | This plugin server instance only runs ingestion (1)                                                                             |
| `PLUGIN_SERVER_MODE=async`     | This plugin server processes all async tasks (2-4). Note that async plugin tasks are triggered based on ClickHouse events topic |

If `PLUGIN_SERVER_MODE` is not set the plugin server will execute all of its tasks (1-4).

## Configuration

There's a multitude of settings you can use to control the plugin server. Use them as environment variables.

| Name                                   | Description                                                                                                                                                                                                    | Default value                         |
| -------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------- |
| DATABASE_URL                           | Postgres database URL                                                                                                                                                                                          | `'postgres://localhost:5432/posthog'` |
| REDIS_URL                              | Redis store URL                                                                                                                                                                                                | `'redis://localhost'`                 |
| BASE_DIR                               | base path for resolving local plugins                                                                                                                                                                          | `'.'`                                 |
| WORKER_CONCURRENCY                     | number of concurrent worker threads                                                                                                                                                                            | `0` – all cores                       |
| TASKS_PER_WORKER                       | number of parallel tasks per worker thread                                                                                                                                                                     | `10`                                  |
| REDIS_POOL_MIN_SIZE                    | minimum number of Redis connections to use per thread                                                                                                                                                          | `1`                                   |
| REDIS_POOL_MAX_SIZE                    | maximum number of Redis connections to use per thread                                                                                                                                                          | `3`                                   |
| SCHEDULE_LOCK_TTL                      | how many seconds to hold the lock for the schedule                                                                                                                                                             | `60`                                  |
| PLUGINS_RELOAD_PUBSUB_CHANNEL          | Redis channel for reload events                                                                                                                                                                                | `'reload-plugins'`                    |
| CLICKHOUSE_HOST                        | ClickHouse host                                                                                                                                                                                                | `'localhost'`                         |
| CLICKHOUSE_DATABASE                    | ClickHouse database                                                                                                                                                                                            | `'default'`                           |
| CLICKHOUSE_USER                        | ClickHouse username                                                                                                                                                                                            | `'default'`                           |
| CLICKHOUSE_PASSWORD                    | ClickHouse password                                                                                                                                                                                            | `null`                                |
| CLICKHOUSE_CA                          | ClickHouse CA certs                                                                                                                                                                                            | `null`                                |
| CLICKHOUSE_SECURE                      | whether to secure ClickHouse connection                                                                                                                                                                        | `false`                               |
| KAFKA_HOSTS                            | comma-delimited Kafka hosts                                                                                                                                                                                    | `null`                                |
| KAFKA_CONSUMPTION_TOPIC                | Kafka incoming events topic                                                                                                                                                                                    | `'events_plugin_ingestion'`           |
| KAFKA_CLIENT_CERT_B64                  | Kafka certificate in Base64                                                                                                                                                                                    | `null`                                |
| KAFKA_CLIENT_CERT_KEY_B64              | Kafka certificate key in Base64                                                                                                                                                                                | `null`                                |
| KAFKA_TRUSTED_CERT_B64                 | Kafka trusted CA in Base64                                                                                                                                                                                     | `null`                                |
| KAFKA_PRODUCER_MAX_QUEUE_SIZE          | Kafka producer batch max size before flushing                                                                                                                                                                  | `20`                                  |
| KAFKA_FLUSH_FREQUENCY_MS               | Kafka producer batch max duration before flushing                                                                                                                                                              | `500`                                 |
| KAFKA_MAX_MESSAGE_BATCH_SIZE           | Kafka producer batch max size in bytes before flushing                                                                                                                                                         | `900000`                              |
| LOG_LEVEL                              | minimum log level                                                                                                                                                                                              | `'info'`                              |
| SENTRY_DSN                             | Sentry ingestion URL                                                                                                                                                                                           | `null`                                |
| STATSD_HOST                            | StatsD host - integration disabled if this is not provided                                                                                                                                                     | `null`                                |
| STATSD_PORT                            | StatsD port                                                                                                                                                                                                    | `8125`                                |
| STATSD_PREFIX                          | StatsD prefix                                                                                                                                                                                                  | `'plugin-server.'`                    |
| DISABLE_MMDB                           | whether to disable MMDB IP location capabilities                                                                                                                                                               | `false`                               |
| INTERNAL_MMDB_SERVER_PORT              | port of the internal server used for IP location (0 means random)                                                                                                                                              | `0`                                   |
| DISTINCT_ID_LRU_SIZE                   | size of persons distinct ID LRU cache                                                                                                                                                                          | `10000`                               |
| CAPTURE_INTERNAL_METRICS               | whether to capture internal metrics for posthog in posthog                                                                                                                                                     | `false`                               |
| PISCINA_USE_ATOMICS                    | corresponds to the piscina useAtomics config option (https://github.com/piscinajs/piscina#constructor-new-piscinaoptions)                                                                                      | `true`                                |
| PISCINA_ATOMICS_TIMEOUT                | (advanced) corresponds to the length of time (in ms) a piscina worker should block for when looking for tasks - instances with high volumes (100+ events/sec) might benefit from setting this to a lower value | `5000`                                |
| HEALTHCHECK_MAX_STALE_SECONDS          | 'maximum number of seconds the plugin server can go without ingesting events before the healthcheck fails'                                                                                                     | `7200`                                |
| MAX_PENDING_PROMISES_PER_WORKER        | (advanced) maximum number of promises that a worker can have running at once in the background. currently only targets the exportEvents buffer.                                                                | `100`                                 |
| KAFKA_PARTITIONS_CONSUMED_CONCURRENTLY | (advanced) how many kafka partitions the plugin server should consume from concurrently                                                                                                                        | `1`                                   |
| PLUGIN_SERVER_MODE                     | (advanced) see alternative modes section                                                                                                                                                                       | `null`                                |

## Releasing a new version

Just bump up `version` in `package.json` on the main branch and the new version will be published automatically,
with a matching PR in the [main PostHog repo](https://github.com/posthog/posthog) created.

It's advised to use `bump patch/minor/major` label on PRs - that way the above will be done automatically when the PR is merged.

Courtesy of GitHub Actions.

## Walkthrough

The story begins with `pluginServer.ts -> startPluginServer`, which is the main thread of the plugin server.

This main thread spawns `WORKER_CONCURRENCY` worker threads, managed using Piscina. Each worker thread runs `TASKS_PER_WORKER` tasks ([concurrentTasksPerWorker](https://github.com/piscinajs/piscina#constructor-new-piscinaoptions)).

### Main thread

Let's talk about the main thread first. This has:

1. `pubSub` – Redis powered pub-sub mechanism for reloading plugins whenever a message is published by the main PostHog app.

1. `hub` – Handler of connections to required DBs and queues (ClickHouse, Kafka, Postgres, Redis), holds loaded plugins.
   Created via `hub.ts -> createHub`. Every thread has its own instance.

1. `piscina` – Manager of tasks delegated to threads. `makePiscina` creates the manager, while `createWorker` creates the worker threads.

1. `pluginScheduleControl` – Controller of scheduled jobs. Responsible for adding Piscina tasks for scheduled jobs, when the time comes. The schedule information makes it into the controller when plugin VMs are created.

    Scheduled tasks are controlled with [Redlock](https://redis.io/topics/distlock) (redis-based distributed lock), and run on only one plugin server instance in the entire cluster.

1. `jobQueueConsumer` – The internal job queue consumer. This enables retries, scheduling jobs in the future (once) (Note: this is the difference between `pluginScheduleControl` and this internal `jobQueue`). While `pluginScheduleControl` is triggered via `runEveryMinute`, `runEveryHour` tasks, the `jobQueueConsumer` deals with `meta.jobs.doX(event).runAt(new Date())`.

    Jobs are enqueued by `job-queue-manager.ts`, which is backed by Postgres-based [Graphile-worker](https://github.com/graphile/worker) (`graphile-queue.ts`).

1. `queue` – Event ingestion queue. This is a Celery (backed by Redis) or Kafka queue, depending on the setup (EE/Cloud is Kafka due to high volume). These are consumed by the `queue` above, and sent off to the Piscina workers (`src/main/ingestion-queues/queue.ts -> ingestEvent`). Since all of the actual ingestion happens inside worker threads, you'll find the specific ingestion code there (`src/worker/ingestion/ingest-event.ts`). There the data is saved into Postgres (and ClickHouse via Kafka on EE/Cloud).

    It's also a good idea to see the producer side of this ingestion queue, which comes from `Posthog/posthog/api/capture.py`. The plugin server gets the `process_event_with_plugins` Celery task from there, in the Postgres pipeline. The ClickHouse via Kafka pipeline gets the data by way of Kafka topic `events_plugin_ingestion`.

1. `mmdbServer` – TCP server, which works as an interface between the GeoIP MMDB data reader located in main thread memory and plugins ran in worker threads of the same plugin server instance. This way the GeoIP reader is only loaded in one thread and can be used in all. Additionally this mechanism ensures that `mmdbServer` is ready before ingestion is started (database downloaded from [http-mmdb](https://github.com/PostHog/http-mmdb) and read), and keeps the database up to date in the background.

### Worker threads

This begins with `worker.ts` and `createWorker()`.

`hub` is the same setup as in the main thread.

New functions called here are:

1. `setupPlugins` – Loads plugins and prepares them for lazy VM initialization.

2. `createTaskRunner` – Creates a Piscina task runner that allows to operate on plugin VMs.

> Note:
> An `organization_id` is tied to a _company_ and its _installed plugins_, a `team_id` is tied to a _project_ and its _plugin configs_ (enabled/disabled+extra config).

## Questions?

### [Join our Slack community. 🦔](https://posthog.com/slack)
