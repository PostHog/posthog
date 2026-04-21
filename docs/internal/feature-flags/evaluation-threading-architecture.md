# Flag evaluation threading architecture

This document explains the threading architecture behind the Feature Flags Rust service's flag evaluation pipeline. The design addresses a specific failure mode that was observed in production: heavy flag evaluation requests were starving the Tokio runtime, which froze the entire application because it could no longer serve HTTP traffic or execute I/O.

The solution separates concerns across two thread pools (Tokio for I/O, Rayon for CPU-bound work) and introduces a semaphore-based backpressure mechanism to keep the system stable under load.

## Background: why two thread pools

The feature flags service is an async Rust application built on [Tokio](https://tokio.rs/). Tokio provides a multi-threaded runtime that schedules async tasks (futures) across a pool of worker threads. Each worker thread runs an event loop: it polls futures until they yield (at an `.await` point), then picks up another future that is ready to make progress. This cooperative scheduling model works well when tasks spend most of their time waiting for I/O (network calls, database queries, Redis lookups), because a small number of threads can handle thousands of concurrent connections by simply parking one task and advancing another while the first one waits.

The problem appears when a task performs CPU-bound work without yielding. When a Tokio worker thread is busy computing something (say, evaluating hundreds of feature flag conditions), it cannot poll other futures. If enough worker threads are blocked simultaneously, the runtime runs out of threads to drive I/O, and the whole service freezes: health checks time out, new connections are not accepted, and in-flight requests stall.

This is exactly what happened in production. A single `/flags` request can ask the service to evaluate hundreds of flags for a given user. Each flag evaluation involves hashing, condition matching, and property lookups — all CPU work. When several such requests arrived concurrently, they consumed all available Tokio workers and left none free to handle the I/O that lighter requests depended on.

The fix introduces a second thread pool — [Rayon](https://docs.rs/rayon/) — dedicated to CPU-bound flag evaluation. When a request involves a large batch of flags, the evaluation work is moved off the Tokio runtime entirely. The Tokio worker that received the request simply awaits a result from Rayon, freeing itself to handle other I/O-bound work in the meantime.

## Thread pool sizing

Both pools are initialized in `main()` before the async runtime starts (`rust/feature-flags/src/main.rs`):

```rust
let threads = ThreadCounts::new(config.thread_pool_cores);

rayon::ThreadPoolBuilder::new()
    .num_threads(threads.rayon_threads)
    .build_global()
    .expect("failed to create rayon thread pool");

let tokio_runtime = tokio::runtime::Builder::new_multi_thread()
    .worker_threads(threads.tokio_workers)
    .enable_all()
    .build()
    .expect("failed to create tokio thread pool");
```

The `ThreadCounts` struct (`rust/feature-flags/src/config.rs`) computes thread counts from the available core count:

- **Tokio workers** = `cores / 2` (minimum 1). Tokio threads spend most of their time parked in `.await`, so half the core count is sufficient.
- **Rayon threads** = `cores` (minimum 1). Rayon handles CPU-bound parallel evaluation, so it receives the full core count.

This means the total thread count slightly oversubscribes the CPU (e.g., 5 Tokio + 10 Rayon = 15 threads on 14 cores for US). This is safe in practice because Tokio threads are mostly idle, so the actual concurrent CPU demand rarely exceeds the physical core count.

The core count can be overridden via the `THREAD_POOL_CORES` environment variable. When set to 0 (the default), the service reads `std::thread::available_parallelism()`, which in a Kubernetes environment reflects the CFS quota (CPU limit), not the CPU request. In production, this override is used explicitly (e.g. `THREAD_POOL_CORES=10` in US, `THREAD_POOL_CORES=8` in EU) to control oversubscription precisely.

## The evaluation threshold

Not all requests need the Rayon pool. Most `/flags` requests evaluate a modest number of flags (typically around 50), and for these the overhead of dispatching work to Rayon — cloning data, crossing thread boundaries, acquiring a semaphore permit — would cost more than it saves.

The decision is made in `evaluate_flags_in_level()` (`rust/feature-flags/src/flags/flag_matching.rs`):

```rust
let eval_type = if flags_to_evaluate.len() >= self.parallel_eval_threshold {
    EvaluationType::Parallel
} else {
    EvaluationType::Sequential
};
```

The threshold is controlled by `PARALLEL_EVAL_THRESHOLD` (default: 100, set to 200 in US production). Below this count, flags are evaluated sequentially on the Tokio worker thread that received the request. At or above this count, the batch is dispatched to Rayon.

### Sequential evaluation

In the sequential path, the code iterates over flags by reference and evaluates them one by one:

```rust
EvaluationType::Sequential => {
    flags_to_evaluate.iter().for_each(|flag| {
        let result = self.evaluate_single_flag(
            flag,
            &precomputed_property_overrides,
            flags_with_missing_deps,
            hash_key_overrides,
            request_hash_key_override,
        );
        self.process_flag_result(
            flag,
            &result,
            &mut level_evaluated_flags_map,
            &mut errors_while_computing_flags,
        );
    });
}
```

This path has no coordination overhead: no cloning, no semaphore, no cross-thread communication. Flags are borrowed by reference, so there is no additional memory allocation. The tradeoff is that the Tokio worker is occupied for the duration of the evaluation, but for small batches this is fast enough that it does not cause starvation.

### Parallel evaluation

When the batch is large enough to warrant parallelization, `evaluate_batch_parallel()` is called. This function performs several steps that are worth understanding in detail.

**Cloning and snapshot preparation.** Because the work will run on a different thread pool, all data must be moved into the closure. The matcher, flags, overrides, and dependency information are cloned. Additionally, lightweight `FlagSnapshot` objects are saved for each flag before moving them into Rayon. These snapshots are used as a fallback if the Rayon task panics: they allow the service to construct error results for every flag rather than silently dropping flags from the response.

**The work closure.** The actual evaluation happens inside a closure that uses Rayon's `into_par_iter()`:

```rust
let work = move || {
    flags_to_evaluate
        .into_par_iter()
        .map(|flag| {
            let _guard = install_rayon_canonical_log();
            let result = matcher.evaluate_single_flag(
                &flag,
                &precomputed_property_overrides,
                &missing_deps,
                &hash_overrides,
                &req_hash_override,
            );
            let delta = take_rayon_canonical_log();
            (flag, result, delta)
        })
        .collect::<Vec<_>>()
};
```

`into_par_iter()` is Rayon's parallel iterator. It splits the collection of flags across Rayon's worker threads using a work-stealing strategy: each thread takes a chunk of flags and evaluates them, and if one thread finishes early it steals work from another thread's queue. The canonical log (used for structured request logging) is maintained per-thread using thread-local storage, and the deltas are collected alongside each flag's result to be merged back into the request's task-local log after the parallel work completes.

**Dispatching through the `RayonDispatcher`.** The closure is not sent to Rayon directly. It goes through the `RayonDispatcher`, which is the backpressure mechanism described in the next section:

```rust
let result = match &self.rayon_dispatcher {
    Some(dispatcher) => dispatcher
        .try_spawn(work)
        .await
        .map_err(|t| FlagError::RayonSemaphoreTimeout(t.waited.as_millis() as u64))?,
    // ...
};
```

If the semaphore times out, the request fails with a `RayonSemaphoreTimeout` error, which is converted to an HTTP 504. This is intentional: the ingress layer can then retry the request on a different, less-loaded pod.

## The `RayonDispatcher`: backpressure and the Tokio-Rayon bridge

The `RayonDispatcher` (`rust/feature-flags/src/rayon_dispatcher.rs`) solves two problems at once: it bridges the async Tokio world with the synchronous Rayon world, and it prevents unbounded queueing on the Rayon pool.

### Why backpressure matters

Rayon's `spawn()` function places work onto an internal injector queue. This queue is unbounded. Under sustained load, if requests arrive faster than Rayon can process them, the queue grows without limit. This causes two compounding problems:

1. **Queueing delay dominates latency.** Each new batch waits behind all previously queued batches. Even if individual evaluations are fast, the queue wait pushes p99 latency up.

2. **Work-stealing degrades.** Rayon's `into_par_iter()` splits work across available threads using work-stealing. When many batches are in flight simultaneously, each batch gets fewer threads to steal from, so per-batch latency increases — which makes the queue drain slower, compounding the problem.

The `RayonDispatcher` addresses this by interposing a `tokio::sync::Semaphore` that limits the number of batches that can be in flight on the Rayon pool at any time. When all permits are held, new requests suspend (`.await`) on the Tokio side, yielding the Tokio worker thread so it can serve other requests while waiting.

### How it works

The dispatcher is a small struct wrapping an `Arc<Semaphore>` and an optional timeout:

```rust
pub struct RayonDispatcher {
    semaphore: Arc<Semaphore>,
    timeout: Option<Duration>,
}
```

The core method is `dispatch()`, which bridges Rayon and Tokio using a `oneshot` channel:

```rust
async fn dispatch<F, R>(permit: OwnedSemaphorePermit, work: F) -> Option<R>
where
    F: FnOnce() -> R + Send + 'static,
    R: Send + 'static,
{
    let (tx, rx) = tokio::sync::oneshot::channel();

    rayon::spawn(move || {
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(work));

        drop(permit);  // Release permit BEFORE sending result

        if let Ok(value) = result {
            drop(tx.send(value));
        }
        // On panic: tx is dropped without sending → rx yields None
    });

    rx.await.ok()
}
```

The flow is:

1. A `oneshot` channel is created. The sender (`tx`) goes into the Rayon closure; the receiver (`rx`) stays on the Tokio side.
2. `rayon::spawn()` enqueues the closure onto Rayon's injector queue. Once a Rayon worker picks it up, it executes the work closure.
3. The work is wrapped in `catch_unwind` to handle panics gracefully. If the closure panics, `tx` is dropped without sending, and `rx.await` returns `None`.
4. The semaphore permit is dropped **before** sending the result. This ordering matters: it ensures that when `rx.await` completes on the Tokio side, the permit has already been released, making `rx.await` a reliable synchronization point for backpressure.
5. On the Tokio side, the worker that dispatched the work simply `.await`s on `rx`. This suspends the future and frees the Tokio worker to do other work. When the Rayon task completes and sends the result, the future is woken up and processing continues.

### Semaphore sizing

The number of semaphore permits controls how many parallel evaluation batches can run on Rayon simultaneously. By default, it is computed as `ceil(rayon_threads / 3)`:

```rust
pub fn default_max_concurrent_batch_evals(&self) -> usize {
    self.rayon_threads.div_ceil(3).max(1)
}
```

The goal is to keep roughly 3 Rayon threads available per concurrent batch. With fewer threads per batch, `into_par_iter()` degrades toward sequential execution because there are not enough threads for meaningful work-stealing. For example, with 10 Rayon threads, this gives 4 permits, meaning each batch gets about 2–3 threads on average.

This value can be overridden via `MAX_CONCURRENT_BATCH_EVALS`.

### Timeout and load shedding

The dispatcher supports an optional timeout via `RAYON_SEMAPHORE_TIMEOUT_MS`. When configured (non-zero), if a request cannot acquire a semaphore permit within the timeout, it receives a `SemaphoreTimeout` error, which is converted to HTTP 504. The ingress layer (Envoy/nginx) can then retry the request on a different pod, effectively distributing load away from overloaded instances.

When set to 0 (the default), requests wait indefinitely for a permit.

## Dependency levels and evaluation stages

Flag evaluation is not a flat loop. Flags can depend on other flags (e.g., flag A's condition may check whether flag B evaluates to true). The service handles this by building a precomputed dependency graph and evaluating flags in topological order, stage by stage.

Each stage contains flags whose dependencies have already been evaluated in prior stages. The sequential-vs-parallel decision is made independently for each stage, based on how many flags that stage contains.

This means a single request might use sequential evaluation for one stage (few flags) and parallel evaluation for another (many flags). When this happens, the request's evaluation type is "promoted" to `Parallel`, because the `promote()` function makes `Parallel` sticky: once any stage uses parallel evaluation, the request is labeled as parallel for metrics purposes.

```rust
pub fn promote(current: Option<Self>, level_type: Self) -> Option<Self> {
    match (current, level_type) {
        (_, Self::Parallel) => Some(Self::Parallel),
        (None, Self::Sequential) => Some(Self::Sequential),
        (current, Self::Sequential) => current,
    }
}
```

## Property fetching

Before flag conditions are evaluated, the service needs to load user properties from the database. This involves up to three queries, all running sequentially on a single database connection:

1. **Person query**: fetches the person record (ID, UUID, properties) by joining `posthog_persondistinctid` with `posthog_person`.
2. **Cohort query**: fetches static cohort membership for the person. This depends on the person query because it needs `person_id`, so it must run after it.
3. **Group query**: fetches group properties when the request involves group-based flags.

All three queries share the same connection acquired from the `persons_reader` pool. The person query runs first, and if a person is found and there are static cohort IDs to check, the cohort query runs next using the `person_id` from the first result. Finally, if the request involves group-based flags, the group query runs.

This sequential approach means the total property fetch time is the sum of all individual query times. The group query is logically independent of the person and cohort queries, which makes it a candidate for future parallelization, but today it runs in sequence on the same connection.

## The full request lifecycle

Putting it all together, a `/flags` request flows through the following stages:

1. **HTTP handler** receives the request and extracts the `RayonDispatcher` from the shared application state.

2. **Dependency graph construction**: the service builds a `PrecomputedDependencyGraph` that organizes flags into evaluation stages based on their dependencies.

3. **Property prefetch**: if any flags require database-sourced properties (person, cohort, or group), the service fetches them sequentially on a single database connection.

4. **Stage-by-stage evaluation**: for each dependency stage:
   - Count the flags to evaluate.
   - If below the threshold: evaluate sequentially on the Tokio worker.
   - If at or above the threshold: dispatch to Rayon through the `RayonDispatcher`.
     - Acquire a semaphore permit (suspending if all permits are held).
     - Send the work closure to Rayon via `rayon::spawn`.
     - Await the result via a `oneshot` channel.
     - Merge per-thread canonical log deltas back into the request's log.

5. **Response construction**: results from all stages are merged into a `FlagsResponse` and returned to the caller.

## Configuration reference

| Variable                     | Default        | Description                                                                                                                      |
| ---------------------------- | -------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `THREAD_POOL_CORES`          | 0 (auto)       | Override the core count used for thread pool sizing. When 0, reads `available_parallelism()` (CFS quota in K8s).                 |
| `PARALLEL_EVAL_THRESHOLD`    | 100            | Minimum number of flags in a stage to trigger parallel evaluation. Below this, evaluation runs sequentially on the Tokio worker. |
| `MAX_CONCURRENT_BATCH_EVALS` | 0 (auto)       | Maximum concurrent batches on the Rayon pool (semaphore permit count). When 0, computed as `ceil(rayon_threads / 3)`.            |
| `RAYON_SEMAPHORE_TIMEOUT_MS` | 0 (no timeout) | Maximum wait time for a Rayon semaphore permit. When exceeded, returns HTTP 504 for ingress retry.                               |

## Observability

The `RayonDispatcher` emits several metrics to help diagnose backpressure and pool saturation:

- `flags_rayon_dispatcher_semaphore_wait_ms`: histogram of how long requests wait for a semaphore permit. Near-zero values mean the pool is not saturated; high values indicate queueing.
- `flags_rayon_dispatcher_available_permits`: gauge of permits not currently held. Persistently zero means the pool is fully saturated.
- `flags_rayon_dispatcher_execution_ms`: histogram of actual execution time on the Rayon pool, excluding wait time.
- `flags_rayon_dispatcher_contended_acquires_total`: counter of acquisitions that had to wait because no permit was immediately available. The ratio of contended to total acquisitions gives the contention rate.
- `flags_rayon_dispatcher_acquires_total`: counter of total semaphore acquisitions.
- `flags_rayon_dispatcher_inflight_tasks`: gauge of tasks currently executing on the Rayon pool.
- `flags_rayon_dispatcher_semaphore_timeouts_total`: counter of requests that timed out waiting for a permit.

Additionally, the evaluation type (`sequential` or `parallel`) is recorded as a label on the `FLAG_REQUESTS_COUNTER` and `FLAG_REQUESTS_LATENCY` metrics, making it possible to compare latency distributions between the two paths.
