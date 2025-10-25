# Temporal

PostHog uses Temporal to power multiple products and features like:

- All of Batch exports,
- Syncs for data warehouse,
- Processing AI agent conversations,
- Data warehouse model materialization,
- And more...

All these products and features require a scheduling and orchestration system with idempotent execution, granular error management, and an observable history for debugging and maintenance. All while also being distributed across a scalable number of workers.

Temporal provides us with abstractions that handle the distributed execution while looking like local code, which means we can focus on writing application code as if it were running locally. This is not without a cost: When using Temporal, you accrue a maintenance burden and increased complexity, partly because distributed systems are hard and partly because the Temporal abstractions are not leak-proof. So, if you are considering Temporal, you should evaluate the reliability, idempotency, and observability requirements of your application against the maintenance load and increased complexity to decide if Temporal represents a worthy trade-off.

That being said, if you do decide to develop an application or feature with Temporal, this README will guide you through how we develop with Temporal, common pitfalls, and useful additional abstractions we have developed over time.

## Temporal concepts

Let's begin with describing basic Temporal concepts.

### Workflow

A workflow is a sequence of activities, that usually have some dependency relation between each other. If you are familiar with Apache Airflow, a Temporal workflow is analogous to an Airflow DAG. A workflow is code: We use the Temporal SDK to write workflows, currently in Python but SDKs are available for other languages too.

More concretely, workflows are Python classes decorated with `temporalio.workflow.defn` that have a method decorated with `temporalio.workflow.run`. This method is the entry-point of our workflow. Throughout the method, workflows implement business logic, call activities with `workflow.execute_activity`, and aggregate any results before returning. Workflow code runs in a custom `asyncio` event loop implemented by Temporal and must be deterministic. Concretely, this means there are restrictions on the code that can run in a workflow. The most common restriction you will run into is that all I/O calls cannot run in the workflow itself, and must be delegated to an activity instead.

Here is a very simple workflow:

```python
import asyncio
from temporalio import activity, workflow
from temporalio.client import Client


@activity.defn
async def hello_world_activity() -> str:
    return "Hello world!"


@workflow.defn
class HelloWorldWorkflow:
    @workflow.run
    async def run(self) -> str:
        return await workflow.execute_activity(hello_world_activity)


async def main():
    client = await Client.connect("localhost:7233")
    result = await client.execute_workflow(HelloWorldWorkflow.run, id="my-workflow-id", task_queue="my-task-queue")
    print(f"Result: {result}")

if __name__ == "__main__":
    asyncio.run(main())
```

> [!TIP]
> You can find more examples of workflows throughout this repository by looking for the `@workflow.defn` decorator.

### Activity

An activity represents a single operation executed by a workflow. Again, if you are familiar with Apache Airflow, activities are analogous to tasks. Like workflows, activities are also code: using the Python SDK, we decorate functions with `temporalio.activity.defn` to mark them as activities.

There are three types of activities:

1. Coroutines (`async def` functions),
2. Synchronous multithreaded functions,
3. And synchronous multiprocessing functions.

When using the Python SDK, coroutines are the recommended default for better performance, and require no extra setup. However, a specific product or feature may require executing tasks that are not well suited for `asyncio`, like a computation-heavy CPU-bound workload. For these situations, activities can be written as synchronous functions that, depending on how the Temporal workers are configured, will run in either a thread pool, or a process pool.

If an activity is prone to experience temporary disruptions, it can be configured to be retried automatically by Temporal.

### Temporal service

The Temporal service acts as the orchestrator of all workflows and activities. This service ensures workflows are durable such that they persist even if workers crash. The service achieves this by keeping track of the execution progress of a workflow, which also enables automated retrying when any activities fail. Developers can inspect this history if required to debug their workflows.

At PostHog, we rely on [Temporal Cloud](https://cloud.temporal.io) to host the Temporal service. If you require access to Temporal Cloud, you can request it via the usual help channels.

### Worker

Workflows and activities run in Temporal workers. The Temporal service assigns workflow and activity execution to different task queues, depending on how they are configured in our code, and workers poll these queues to execute the workflow and activity code. The workers are also configured in code as they are also provided by the Temporal Python SDK.

> [!NOTE]
> A worker can only listen to a single queue.

At PostHog, most of the configuration currently happens in this package, particularly in the `worker.py` module.

### Schedule

Temporal schedules are defined by: the action to execute, a spec, a state, and a policy.

The action a schedule can take is always starting a workflow. This is configured with the `temporalio.client.ScheduleActionStartWorkflow` class which defines which workflow to run, with which arguments and id, in which task queue, and the retry policy for the workflow.

> [!NOTE]
> The workflow ID configured functions more as an ID prefix: the Temporal schedule will append the start time of the workflow to the end of the ID.

The schedule spec, configured with `temporalio.client.ScheduleSpec` defines the interval or intervals our schedule will run on. The `start_at` and `end_at` parameters determine the beginning and the end of the schedule itself: This means that no runs will be created before `start_at` and no runs will be created after `end_at`. Both can be `None` if we want our schedule to schedule runs forever until paused or deleted.

> [!CAUTION]
> Temporal automatically cleans up schedules sometime after their `end_at` has passed. It is generally not required to set an `end_at` but if you do consider that this means the schedule will be automatically deleted from the Temporal service without possibility of restoring it.

There are multiple ways to define the intervals a schedule runs on: By setting the `intervals` argument, we pass a collection of `datetime.timedelta` of objects which determine the delta between runs, alternatively the `calendars` argument allows matching on date components, like `day_of_month` or `day_of_week`.

> [!IMPORTANT]
> By default, calendar-based expressions are interpreted in UTC. The `time_zone_name` argument can override this.

The schedule spec can also include a `jitter` to apply a random value to the start time of each run. This is useful when having multiple schedules with the same spec, as it can help avoid all runs starting simultaneously which can lead to the thundering herd problem on any services those workflows use.

The state of the schedule as defined by `temporalio.client.ScheduleState` simply sets whether the schedule is paused or not. A paused schedule will not run any actions until unpaused.

Finally, the schedule's policy (`temporalio.client.SchedulePolicy`) determines whether to allow or not IDs to overlap, which is useful for backfilling schedules, and whether to pause a schedule on failure.

```python
import uuid

from temporalio.common import RetryPolicy
from temporalio.client import (
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleIntervalSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
    ScheduleState,
)

from posthog.temporal.common.schedule import a_create_schedule
from products.my_product.workflows import my_workflow, MyWorkflowInputs


my_inputs = MyWorkflowInputs(...)
my_retry_policy = RetryPolicy(...)
my_task_queue = "general-purpose-task-queue"
workflow_id = str(uuid.uuid4())

schedule = Schedule(
    action=ScheduleActionStartWorkflow(
        workflow=my_workflow,
        args=my_inputs,
        id=workflow_id,
        task_queue=my_task_queue,
        retry_policy=my_retry_policy,
    ),
    spec=ScheduleSpec(
        intervals=[ScheduleIntervalSpec(every=...)],
        jitter=...,
    ),
    state=ScheduleState(),
    policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.ALLOW_ALL),
)
```

## Implement a product or feature with Temporal

The first step when working with Temporal is deciding whether Temporal is the right tool for the job. If the application and/or feature you are implementing requires offloading work to specialized workers that must ensure durability and idempotency, offer tools to manage error handling and retry mechanisms, and you are willing to accept an increase in complexity and maintenance burden then Temporal could be the right tool for the job. Once you chosen Temporal, you will be please to know that a lot of our work here is making that increase complexity and maintenance burden small and easier to manage, so you get to re-use some of the tooling we have built when developing other products. _Yay!_

Let's now dive into some of the decisions you will need to take when developing a product or feature with Temporal.

### Decide what type of activity you need

Temporal workers run multiple workflows and activities simultaneously. In order to enable that, we need to choose a concurrency model for our activities and, like described before, there are three types: asyncio, multithreaded, and multiprocessing. This README is not a guide on each concurrency model, so we will focus only on considerations when implementing activities using each of the concurrency models instead.

> [!TIP]
> A workflow can use different concurrency models in each of its activities, meaning we can have a workflow execute a coroutine activity, and then execute a multiprocessing activity. Although, to keep things simple, we would recommend trying to find a single concurrency model that works for all your activities.

> [!TIP]
> Asyncio is usually the best choice.

#### Asyncio

The most important rule when writing asyncio code is: **DO NOT BLOCK** the event loop. Asyncio is the optimal choice for code that is bound by I/O operations, like network or database requests. However, it is of utmost importance that those requests are done using non-blocking primitives. Otherwise, no tasks will be executing concurrently in the worker, and any performance benefit of using asyncio is lost. Moreover, the same event loop is also used to run other activities in the worker which can also be blocked and eventually timed-out.

Asyncio is not new in Python (originally introduced in 3.4, and the new keywords in 3.5), but it has not been widely adopted in PostHog (yet!). This means that there isn't much code we can re-use from the PostHog monolith within Temporal activities. In particular, Django models will issue blocking requests when using the same method calls used anywhere else in PostHog. For this reason, more often than not, some amount of work is required to bring code from other parts of PostHog into activities:

- Sometimes, the library you need to use has adopted asyncio and offers methods that can be a drop-in replacement.
  - For example: Django models have async methods that just append `a` to the front: `MyModel.objects.get(...)` becomes `await MyModel.objects.aget(...)`. But not all the Django model API has support for asyncio, so check the documentation for our current version of Django.
- If the library you require doesn't support asyncio, an alternative may exist.
  - For example: The popular `requests` is blocking, but multiple alternatives with asyncio support exist, like `aiohttp` and `httpx`, and generally the API is quite similar, and doesn't require many code changes.
  - Another example: The `aioboto3` implements asyncio support for `boto3`.
  - One more: The `aiokafka` provides consumer and producer classes with non-blocking methods to interact with Kafka.
- If none of the above, you could get around by running blocking code in a thread pool using `concurrent.futures.ThreadPoolExecutor` or just `asyncio.to_thread`.
  - Python releases the GIL on an I/O operation, so you can send that code to a different thread to avoid blocking the main thread with the asyncio event loop.
- Similarly, if the blocking code is CPU bound, you could try using a `concurrent.futures.ProcessPoolExecutor`.
- If nothing worked, you will need to re-implement the code using asyncio libraries and primitives.

Now that your code is using asyncio, it will run in the Temporal workers cooperating with everyone else to execute concurrently.

> [!TIP]
> Having asyncio code opens up the door to applying _asyncio patterns_ that go beyond adding an `await` and changing a method: That group of sequential requests could run concurrently if you wrap them in tasks and `asyncio.gather` or in an `asyncio.TaskGroup`, maybe that progress update request can be done as a background task while the rest of the application carries on, perhaps the data processing can be done as the data arrives using a `asyncio.Queue` in a consumer-producer pattern. Now you are using _asyncio patterns_ instead of running sequential code with `await`s sprinkled around it.

#### Multithreading

It is not recommended to run synchronous multithreading activities. Any threading needs can be satisfied by a thread pool in asynchronous activities, for example by using `asyncio.to_thread`. Regardless, if you have strong reasons to prefer multithreading, then know that making an activity function synchronous is enough as our workers are configured with a thread pool executor by default. However, do note that spawning threads will use up more resources than asyncio, and that a lot of the abstractions we have built on top of the Temporal API are built with asyncio in mind, so it requires additional wrapping to enable certain functions from synchronous code.

Similar considerations around blocking as in asyncio exist here too: The GIL will prevent other activities from running unless released, so your threaded code should contain I/O operations that release the GIL for this concurrency model to make sense.

Using synchronous activities means that you have to opt for synchronous versions of all of our abstractions, like `HeartbeaterSync` instead of `Heartbeater`.

### Set timeouts for your activities

Temporal allows us to apply multiple timeouts to activities:

1. Schedule-to-close: Time out based on the time from the moment the Temporal service puts an activity task in its queue.
2. Start-to-close: Time out based on the time from the moment a worker starts executing an activity.
3. Schedule-to-start: Time out based on the time it takes for an activity to be picked up by a worker.
4. Heartbeat: Time out based on time between heartbeats.

Every activity **must** have at least one of schedule-to-close and start-to-close timeouts defined, and I recommend the latter. This is how the Temporal service recovers after worker crashes: After the timeout expires, the service will re-issue the activity so that it can be picked up by surviving workers.

### Emit heartbeats from your activities

However, for long-running activities, these two timeouts are not enough: Imagine an activity that we expect to take 1 hour to complete, so we set a `start_to_close` timeout of 1 hour. If the worker crashes as soon as the activity begins, we will need to wait almost the full hour until the time out expires and the service re-schedules it. This is too long: We essentially wasted that whole hour, and potentially are now backed up as the new hour begins and we have a new workflow starting. This is why heartbeating and heartbeat timeouts are strongly recommended for any long running activities. By emitting heartbeats, the activities let the service know that they are still alive, and when they stop heartbeating for the duration of the timeout the service knows that the worker has likely crashed and the activity can be retried immediately, without waiting the full start-to-close timeout.

Implementing heartbeating is very easy with the help of the `posthog.temporal.common.heartbeat.Heartbeater` class. This can be used as a context manager to wrap your long running work. `Heartbeater` will schedule a task that issues a heartbeat to the Temporal service within your configured `heartbeat_timeout`.

Hearbeats can include additional arbitrary information in them. This is known as the heartbeat's details. Anything passed is persisted in Temporal and can be obtained later. This can enable progress tracking using heartbeats, but keep in mind that heartbeat delivery is buffered and not guaranteed. For general tracking purposes including details in the heartbeat can be useful, but for precise controls we recommend looking somewhere else.

### Configure retries for your activities

When an activity fails, it may be retried. This will depend on the configured `RetryPolicy` which determines the number of maximum attempts allowed and retry intervals. This can be useful to implement common retry policies, like exponential backoff. Moreover, a `RetryPolicy` also defines a list of errors that should be considered non-retryable and thus they won't be retried even if there are attempts left. This is useful to define fatal errors that won't be resolved by simply retrying.

> [!IMPORTANT]
> Temporal matches errors based on the exception class name. This is likely due to serialization/deserialization reasons (remember everything is distributed!). This means that when setting `non_retryable_error_types` you will have to use the name of all the exception you want to not retry on, and not a common ancestor in the class hierarchy.

By default activities retry forever.

> [!CAUTION]
> Retrying forever literally means forever. Even as the universe compresses again into almost nothing, the few gravitational waves still traveling through will contain enough information to retry your activity. Consider whether it is acceptable to have activities eventually fail, or otherwise setup alerting to spot and manually handle activities that will never succeed.

> [!TIP]
> Always set `max_retries` in tests.

Here is an example showcasing all of the above, but more can be found by searching the codebase:

```python
import asyncio
import datetime as dt

from temporalio import activity, workflow
from temporalio.common import RetryPolicy

from posthog.temporal.common.heartbeat import Heartbeater


class FatalError(Exception):
    ...


class UserFatalError(FatalError):
    ...


class InternalFatalError(FatalError):
    ...


@activity.defn
async def short_activity() -> None:
    # No heartbeating required if we have a short timeout.
    await do_short_work()


@activity.defn
async def long_running_activity() -> None:
    # Long running activities should always heartbeat.
    async with Heartbeater():
        await do_long_work()


@workflow.defn
class HelloWorldWorkflow:
    @worklfow.run
    async def run(self) -> None:
        await workflow.execute_activity(
            short_activity,
            start_to_close_timeout=dt.timedelta(seconds=60),
            # No maximum_attempts means retry forever.
            retry_policy=RetryPolicy(
                initial_interval=dt.timedelta(seconds=2),
                maximum_interval=dt.timedelta(seconds=10),
                non_retryable_error_types=["InternalFatalError"],
            ),
        )

        await workflow.execute_activity(
            long_running_activity,
            start_to_close_timeout=dt.timedelta(hours=2),
            heartbeat_timeout=dt.timedelta(seconds=30),
            retry_policy=RetryPolicy(
                initial_interval=dt.timedelta(seconds=2),
                backoff_coefficient=2.0,
                maximum_interval=dt.timedelta(seconds=64),
                maximum_attempts=10,
                # We set all the possible error types, not a common ancestor.
                non_retryable_error_types=["InternalFatalError", "UserFatalError"],
            ),
        )
```

### Logging

Like the rest of PostHog, logging in Temporal is configured to use [structlog](https://www.structlog.org/en/stable/). In contrast to the rest of PostHog, the structlog configuration defined in `posthog/temporal/common/logger.py` is more complex as it supports two logging modes:

- Write: Logs are written to stdout. These are logs meant to be ingested by internal logging parsers and monitoring systems.
- Produce: Logs are produced to Kafka and later consumed by ClickHouse in the `log_entries` table. This enables querying of logs in PostHog to, for example, communicate to users directly from a Temporal activity or workflow. As an example of this, check how the batch exports logs tab is used to offer debug information to users to allow them to fix configuration errors.

By default, the logger you get from `structlog.get_logger` is configured to do both writing and producing.

> [!NOTE]
> Do note that producing logs requires extra configuration to fit the `log_entries` table schema:
>
> - A `team_id` must be set somewhere in the context.
> - The function `resolve_log_source` in `posthog/temporal/common/logger.py` must be configured to resolve a `log_source` from your workflow's ID and type.
>   That being said, we want logging to be there when you need it, but otherwise get out of the way. For this reason, writing logs to stdout will always work, regardless of whether the requirements for log production are met or not. Moreover, if the requirements for log production are not met, log production will not crash your workflows.

> [!TIP]
> If you don't care about log production, you can use `get_write_only_logger` from `posthog/temporal/common/logger.py` to obtain a logger that only writes to stdout. `get_produce_only_logger` works analogously.

`get_logger` is meant to be called only **once** at the top of your module. If you are going to be logging several times, call `bind` on the global loggers at the top of your activity and/or workflow to avoid the global lookup. The `bind` method also allows binding variables to the logger itself.

```python
import dataclasses

from structlog import get_logger
from structlog.contextvars import bind_contextvars
from temporalio import activity, workflow


# Loggers initialized only once in module scope.
LOGGER = get_logger()  # Takes a name for the logger, leave empty for module name


@activity.defn
async def my_activity_with_lots_of_logging(inputs: MyActivityInputs):
    # All loggers from here on will have `user_id` in the context.
    # The context is copied over to new tasks and threads.
    bind_contextvars(user_id=inputs.user_id)

    # We `bind()` as we will be logging a lot, and global lookups are expensive!
    logger = LOGGER.bind()
    # Variables can be bound to the logger itself, these would only available to this logger:
    # logger = LOGGER.bind(something="...", another_one="...")

    try:
        ...
    except:
        # Help your fellow PostHog engineers figure out what happened!
        logger.exception("Activity failed", reason="wow much technical")


@activity.defn
async def my_small_activity():
    # Using the global LOGGER has an associated performance cost.
    # But if you are not logging much, this is acceptable.
    LOGGER.info("Finished doing small thing")


@workflow.defn
class MyWorfklow:
    @workflow.run
    async def run(self):
        # Loggers can also be used in workflows
        logger = LOGGER.bind()

        logger.info("Workflow start")
        await workflow.execute_activity(my_small_activity)
        await workflow.execute_activity(my_activity_with_lots_of_logging)
        logger.info("Workflow finished")
```

When developing a workflow or activity, you will most likely want **all** your logs to have Temporal context variables (like `activity_type`, `attempt`, or `workflow_id`). Thus, the logging pipeline is configured to **automatically** populate the context with the activity's or workflow's information. All the logs from the previous example would have these variables set in the context.

This logging pipeline also works locally, both when running a worker locally either with `mprocs` or manually running `start_temporal_worker.py`, and if you run your unit tests with:

```sh
DEBUG=1 pytest path/to/your/tests.py -s
```

Locally, the logs are rendered by structlog using [Rich](https://rich.readthedocs.io/en/latest/), so you will get a colorful, human-readable, output instead of the JSON structure we use in production.

> [!CAUTION]
> Loggers offer async methods for logging, they are prefixed with an "a", for example `await logger.ainfo`. Under the hood, the logger is spawning a thread to process the log. This comes with a performance overhead in spawning the thread and context switching, that many times is not worth it for the short time the event loop will be blocked when writing. Moreover, async methods do **NOT** work in workflow contexts as Temporal runs workflow code in a custom event loop that does not implement any thread calls.

### Watch for worker shutdowns

As part of normal operations, Temporal workers are often shutdown and restarted (for example, when a new deployment is triggered). When a shutdown request is emitted, workers will wait for activities running in them to finish. However, they won't wait forever: There is a timeout that can range from a few minutes to hours, as configured in the deployment, and after the timeout fires, all activities will be forcibly killed.

Particularly when working with long-running activities, it may be useful to keep track of when workers are shutting down. For example, your activity may choose to save any in-progress state, and exit early, to avoid being forcibly killed and lose all progress. For this scenario, we recommend using the `ShutdownMonitor` utility available in `posthog.temporal.common.shutdown`. This is a context manager that offers a `is_worker_shutdown` method to check whether the worker we are running on is shutting down. It also offers methods to wait for worker shutdown.

However, short running activities in general won't need to concern themselves with this.

## Deploying to production

Once workflows and activities are finished, there are a few more steps required to bring them to production.

### Assign workflows and activities to workers

Once your workflow and activities have been written, it's time to decide which workers will run them. At PostHog, we have multiple sets of Temporal workers running. Each set of workers listens to a particular task queue, which is how we coordinate which workflows and activities will each worker run: By executing your workflows and activities in a certain task queue, only workers from the set of workers configured to poll that task queue will pick up the work.

Since each product has its own requirements when it comes to worker resources and behavior, each product has its own set of workers, and the product team manages the deployment of said workers. For in-development workflows and activities, there exists a set of workers listening on a shared task queue (called `general-purpose-task-queue`). Anybody may use this general task queue, so you can assign your workflows to it while they are still in development. Once your workflows have moved past the prototyping stage, I recommend looking in the [charts](https://github.com/PostHog/charts) repository for the `temporal-worker` package you can use to create your own deployment. With your own set of workers, you can define resource limits of your own, and avoid conflicts with other workflows running in the shared task queue.

Regardless of which task queue and workers are chosen to run your workflows, all workers are configured right here in the code. So, you need to get your workflow classes and your activity functions in the worker configuration based on the task queue you have chosen. This is done by adding your workflows and activities to mappings in the `posthog/management/command/start_temporal_worker.py` script. I recommend that you group all your workflows and activities in a single collection at the top level `__init__.py` of your product package, so that then they can be imported in `start_temporal_worker.py` and added to the mappings.

For example, let's say I have implemented a product in `products/travelling_salesman_solver/` my `products/travelling_salesman_solver/__init__.py` looks like:

```python
from products.travelling_salesman_solver.temporal.workflows import MyWorkflow
from products.travelling_salesman_solver.temporal.activity import my_first_activity, my_second_activity

WORKFLOWS = [MyWorkflow]
ACTIVITIES = [my_first_activity, my_second_activity]
```

Then, I can import these in `start_temporal_worker.py` and add them to `WORKFLOWS_DICT` and `ACTIVITIES_DICT`:

```python
from products.travelling_salesman_solver import WORKFLOWS as TS_WORKFLOWS, ACTIVITIES as TS_ACTIVITIES

...

WORKFLOWS_DICT = {
    ...
    # Or, use a product-specific task queue if it already has its own deployment!
    GENERAL_PURPOSE_TASK_QUEUE: TS_WORKFLOWS
    + ...
}

ACTIVITIES_DICT = {
    ...
    # Or, use a product-specific task queue if it already has its own deployment!
    GENERAL_PURPOSE_TASK_QUEUE: TS_ACTIVITIES
    + ...
}
```

Once the workers are deployed, they will be able to run your workflows and activities.

### Trigger deployments for workers

Some changes in our CI/CD pipeline will be required to ensure your changes are triggering deployments to your Temporal workers. First, when a new deployment of Temporal workers is created, you may want to trigger the deployment on merges to this repository's `master` branch. For that, edit the `container-images-cd.yaml` GitHub workflow and add a new trigger step.

Moreover, notice that in the workflow every trigger step comes after a check step. This step ensures that only certain module changes trigger a worker re-deployment, and not every single change. This is done because restarting workers can be disruptive to workflows running in it, so as a general rule try to minimize the changes that will trigger a re-deployment of workers. You will probably only need the common temporal modules + your product specific modules in the check.

> [!NOTE]
> Temporal workers stop polling for new tasks when a shutdown is initiated, and the deployments can configure a timeout for the shutdown, which can give time for all workflows currently running to finish. Configuring this correctly can minimize the disruption caused by triggering new deployments, but it can be hard to find the right timeout that ensures everything has time to finish without waiting forever.

### Execute workflows

The most straight-forward way to execute a workflow is with the `execute_temporal_workflow` command:

```sh
python manage.py execute_temporal_workflow "no-op" '{"arg": "1", "batch_export_id": "test", "team_id": 2}'
```

This command takes the name of the workflow as its first argument, and any workflow arguments as a JSON as the second parameter.

> [!IMPORTANT]
> This command makes a request to a Temporal service. If developing locally, there is a Temporal service as part of the development stack that is configured automatically for this command to work. However, to execute workflows in production you will need to access a production server to have access to production Temporal services.

> [!CAUTION]
> Make note of the `TEMPORAL_TASK_QUEUE` configured in whichever environment you are running this command in. If the configured task queue is not configured to handle the workflow you are executing this command will fail.

All that being said, a common scenario is that workflows have to be executed regularly on a given interval without manually calling the command. For this, you can use Temporal schedules.

### Schedule workflow to run regularly

Create a Temporal schedule to, well, _schedule_ workflows to run at set intervals. This can be achieved by calling the `create_schedule` method of a Temporal client. Similarly, a schedule can be updated by the `update_schedule` method in the client.

There are examples on how to achieve this throughout the codebase: Batch exports, for example, creates a new schedule every time a batch export is created, other products have a Django management command to initialize all their schedules. The pattern you choose will depend on how your product is set up.

## Develop locally with Temporal

The development stack includes: A Temporal service to act as a local orchestrator, a Temporal UI, and, if you are using `mprocs`, multiple Temporal workers that are started automatically, one per task queue. These workers includes a worker listening on the shared `general-purpose-task-queue`, which can be used for development. If you have deployed a new set of workers, add it to `bin/mprocs.yaml` so that a worker can start automatically for folks doing local development.

Some products or features may require additional configuration, for example: Data warehouse workflows require additional credentials that must be present in the environment (`#team-data-warehouse` can assist with this reached out for help). Check other documentation based on the product you are trying to develop locally for.

As you run workflows, you will be able to see the logs in the worker's logs, and you can go to the Temporal UI at http://localhost:8081 to check on the workflow status.

## Relevant documentation

- [Documentation for the Temporal Python SDK](https://docs.temporal.io/develop/python).
- [Documentation on Temporal schedules](https://docs.temporal.io/evaluate/development-production-features/schedules).
- [Documentation on different types of activities](https://docs.temporal.io/develop/python/python-sdk-sync-vs-async).
- [Temporal Python SDK repository](https://github.com/temporalio/sdk-python).
- [Temporal Python SDK code samples](https://github.com/temporalio/samples-python).

## Examples in PostHog

All of batch exports is built in Temporal, see [example workflows in batch exports](https://github.com/PostHog/posthog/tree/master/products/batch_exports/backend/temporal/destinations).

[Examples on unit testing Temporal workflows](https://github.com/PostHog/posthog/tree/master/products/batch_exports/backend/tests/temporal) are available in the batch exports tests.
