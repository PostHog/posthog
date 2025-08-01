# Temporal

PostHog uses Temporal to power multiple products and features like:
* All of Batch exports,
* Imports for data warehouse,
* Processing AI agent conversations,
* Data warehouse model materialization,
* And more...

All these products and features require a scheduling and orchestration system with idempotent execution, granular error management, and an observable history for debugging and maintenance. All while also being distributed across a scalable number of workers.

Temporal provides us with abstractions that handle the distributed execution while looking like local code, which means we can focus on writing application code as if it were running locally. This is not without a cost: When using Temporal, you accrue a maintenance burden and increased complexity, and the abstractions are not completely leak-proof. So, if you are considering Temporal, you should weight the reliability, idempotency, and observability requirements of your application against the maintenance load and increased complexity to decide if Temporal represents a worthy trade-off.

That being said, if you do decide to develop an application or feature with Temporal, this README will guide you through how we develop with Temporal, common pitfalls, and useful additional abstractions we have developed over time.

## Basic Temporal concepts

Let's begin with describing basic Temporal concepts.

### Workflow

A workflow is a sequence of activities, that usually have some dependency relation between each other. If you are familiar with Apache Airflow, a Temporal workflow is analogous to an Airflow DAG. A workflow is code: We use the Temporal SDK to write workflows, currently in Python but SDKs are available for other languages too.

More concretely, workflows are Python classes decorated with `temporalio.workflow.defn` that have a method decorated with `temporalio.workflow.run`. This method is the entry-point of our workflow. Throughout the method, workflows implement business logic, call activities with `workflow.execute_activity`, and aggregate any results before returning. Workflow code runs in a custom `asyncio` event loop implemented by Temporal and must be deterministic. Concretely, this means there are restrictions on the code that can run in a workflow. The most common restriction you will run into is that all I/O calls cannot run in the workflow itself, and must be delegated to an activity instead.

Here is a very simple workflow:

```python
import asyncio
from temporalio import activity, workflow

@activity.defn
async def hello_world_activity() -> str:
    return "Hello world!"


@workflow.defn
class HelloWorldWorkflow:
    @worklfow.run
    async def run(self) -> str:
        return await workflow.execute_activity(hello_world_activity)


async def main():
    client = await Client.connect("localhost:7233")
    result = await client.execute_workflow(HelloWorldWorkflow.run, id="my-workflow-id", task_queue="my-task-queue")
    print(f"Result: {result}")

if __name__ == "__main__":
    asyncio.run(main())
```

> ![TIP]
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

Workflows and activities run in Temporal workers. The Temporal service assigns workflow and activity execution to different task queues, depending on their configuration, and workers poll these queues to execute the workflow and activity code. The workers are configured in code as they are also provided by the Temporal Python SDK.

At PostHog, most of the configuration currently happens in this package, particularly in the `worker.py` module.

## Implementing a product or feature with Temporal

The first step when working with Temporal is deciding whether Temporal is the right tool for the job. If the application and/or feature you are implementing requires offloading work to specialized workers that must ensure durability and idempotency, offer tools to manage error handling and retry mechanisms, and you are willing to accept an increase in complexity and maintenance burden then Temporal could be the right tool for the job. Once you chosen Temporal, you will be please to know that a lot of our work here is making that increase complexity and maintenance burden small and easier to manage, so you get to re-use some of the tooling we have built out when developing other applications. *Yay!*

Let's now dive into some of the decisions you will need to take when developing a product or feature with Temporal.

### Decide which type of activity you need

Temporal workers run multiple workflows and activities simultaneously. In order to enable that, we need to choose a concurrency model for our activities and, like described before, there are three types: asyncio, multithreaded, and multiprocessing. This README is not a guide on each concurrency model, so we will focus only on how to implement activities using each of the concurrency models instead.

> ![TIP]
> A workflow can use different concurrency models in each of its activities, meaning we can have a workflow execute a coroutine activity, and then execute a multiprocessing activity. Although, to keep things simple, we would recommend trying to find a single concurrency model that works for all your activities.

#### Asyncio

The most important rule when writing asyncio code is: **DO NOT BLOCK** the event loop. Asyncio is the optimal choice for code that is bound by I/O operations, like network or database requests. However, it is of utmost importance that those requests are done using non-blocking primitives. Otherwise, no tasks will be executing concurrently in the worker, and any performance benefit of using asyncio is lost. Moreover, the same event loop is also used to run other activities in the worker which can also be blocked and eventually timed-out.

Asyncio is not new in Python (originally introduced in 3.4, and the new keywords in 3.5), but it has not been widely adopted in PostHog (yet!). This means that there isn't much code we can re-use from the PostHog monolith within Temporal activities. In particular, Django models will issue blocking requests when using the same method calls used anywhere else in PostHog. For this reason, more often than not, some amount of work is required to bring code from other parts of PostHog into activities:
* Sometimes, the library you need to use has adopted asyncio and offers methods that can be a drop-in replacement.
  * For example: Django models have async methods that just append `a` to the front: `MyModel.objects.get(...)` becomes `await MyModel.objects.aget(...)`. But not all the Django model API has support for asyncio, so check the documentation for our current version of Django.
* If the library you require doesn't support asyncio, an alternative may exist.
  * For example: The popular `requests` is blocking, but multiple alternatives with asyncio support exist, like `aiohttp` and `httpx`, and generally the API is quite similar, and doesn't require many code changes.
  * Another example: The `aioboto3` implements asyncio support for `boto3`.
  * One more: The `aiokafka` provides consumer and producer classes with non-blocking methods to interact with Kafka.
* If none of the above, you could get around by wrapping the blocking code in `asyncio.to_thread`.
  * Python releases the GIL on an I/O operation, so you can send that code to a different thread to avoid blocking the main thread.
* If nothing worked, you will need to re-implement the code using asyncio libraries and primitives.

Now that your code is using asyncio, it will run in the Temporal workers cooperating with everyone else to execute concurrently.

> ![TIP]
> Having asyncio code opens up the door to applying *asyncio patterns* that go beyond adding an `await` and changing a method: That group of sequential requests could run concurrently if you wrap it in `asyncio.gather` or in an `asyncio.TaskGroup`, maybe that progress update request can be done as a background task while the rest of the application carries on, perhaps the data processing can be done as the data arrives using a `asyncio.Queue` in a consumer-producer pattern.
> Now you are using *asyncio patterns* instead of running sequential code with `await`s sprinkled around it.

### Timing-out, heart-beating, and retrying activities

Temporal allows us to apply multiple timeouts to activities:
1. Schedule-to-close: Time out based on the time from the moment the Temporal service puts an activity task in its queue.
2. Start-to-close: Time out based on the time from the moment a worker starts executing an activity.
3. Schedule-to-start: Time out based on the time it takes for an activity to be picked up by a worker.
4. Heartbeat: Time out based on time between heartbeats.

Every activity **must** have at least one of schedule-to-close and start-to-close timeouts defined, and I recommend the latter. This is how the Temporal service recovers after worker crashes: After the timeout expires, the service will re-issue the activity so that it can be picked up by surviving workers.

However, for long-running activities, these two timeouts are not enough: Imagine an activity that we expect to take 1 hour to complete, so we set a `start_to_close` timeout of 1 hour. If the worker crashes as soon as the activity begins, we will need to wait almost the full hour until the time out expires and the service re-schedules it. This is too long: We essentially wasted that whole hour, and potentially are now backed up as the new hour begins and we have a new workflow starting. This is why heartbeating and heartbeat timeouts are strongly recommended for any long running activities. By emitting heartbeats, the activities let the service know that they are still alive, and when they stop heartbeating for the duration of the timeout the service knows that the worker has likely crashed and the activity can be retried immediately, without waiting the full start-to-close timeout.

Implementing hearbeating is very easy with the help of the `posthog.temporal.common.heartbeat.Heartbeater` class. This can be used as a context manager to wrap your long running work. `Heartbeater` will schedule a task that issues a heartbeat to the Temporal service within your configured `heartbeat_timeout`.

Once the Temporal service has determined an activity must be retried, it uses the configured `RetryPolicy` to decide when to retry. This can be useful to implement common retry policies, like exponential backoff. Moreover, a `RetryPolicy` also defines a list of errors that should be considered non-retryable. This is useful to define fatal errors that won't be resolved by simply retrying.

> ![NOTE]
> Temporal matches errors based on the exception class name. This is likely due to serialization/deserialization reasons (remember everything is distributed!). This means that when setting `non_retryable_error_types` you will have to use the name of all the exception you want to not retry on, and not a common ancestor in the class hierarchy.

Moreover, the number of times an activity is retried is also configurable, and by default activities retry forever.

> ![CAUTION]
> Retrying forever literally means forever. Even as the universe compress again into almost nothing, the few gravitational waves still traveling through will contain enough information to retry your activity. Consider whether it is acceptable to have activities eventually fail, or otherwise setup alerting to spot and manually handle activities that will never succeed. Notably, when testing, please set `max_retries` to something reasonable.

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

### Assigning workflows and activities to workers

Once your workflow and activities have been written, it's time to decide which workers will run them. At PostHog, we have multiple sets of Temporal workers running. Each set of workers listens to a particular task queue, which is how we coordinate which workflows and activities will each worker run: By executing your workflows and activities in a certain task queue, then the only the set of workers configured to poll that task queue will pick up the work.

Since each product has its own requirements when it comes to worker resources and behavior, each product has its own set of workers and the product team manages the deployment of said workers. The [charts](https://github.com/PostHog/charts) repository contains a package used to create your own deployment.

That being said, for in-development workflows and activities, there exists a set of workers listening on a general task queue. Anybody may use this general task queue, so we recommend that you use it before your work is ready to move on to your own deployment.

Like previously mentioned, workers are configured right here in the code. So, you need to get your workflow classes and your activity functions in the worker configuration based on the task queue you have chosen. This is done by adding your workflows and activities in the `posthog/management/command/start_temporal_worker.py` script. I recommend that you group all your workflows and activities in a single list at the top level `__init__.py` of your product package, so that then they can be imported in `start_temporal_worker.py` and added to the mappings.

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
    # Or, use a product-specific task queue if already created!
    GENERAL_PURPOSE_TASK_QUEUE: TS_WORKFLOWS
    + ...
}

ACTIVITIES_DICT = {
    ...
    # Or, use a product-specific task queue if already created!
    GENERAL_PURPOSE_TASK_QUEUE: TS_ACTIVITIES
    + ...
}
```

Now, once the workers are deployed, they will be able to run your workflows and activities.

### Executing workflows

### Scheduling workflow to run regularly

### Running Temporal locally

The easiest way to get this to work locally is by running `mprocs`. You'll be missing some environment variables to make sure Temporal can properly connect with the S3/Airbyte instances we use to run the jobs locally. Reach out to `#team-data-warehouse` in Slack to get those creds, add them to `.env`, and you're good to go.

You can access Temporal's UI at http://localhost:8081

## Monitoring products and features in Temporal

### Logging

### Metrics

## Relevant documentation

* [Documentation for the Temporal Python SDK](https://docs.temporal.io/develop/python).
* [Temporal Python SDK repository](https://github.com/temporalio/sdk-python).
* [Temporal Python SDK code samples](https://github.com/temporalio/samples-python).
