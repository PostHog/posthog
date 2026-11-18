from concurrent.futures import ThreadPoolExecutor

from products.alerts.backend.judge.contract import MAX_CONCURRENT_MODEL_CALLS

# AI-detector checks hold a thread for the model call, up to a minute each. On the shared
# default pool that would let a slow model stall every alert's database work on the worker,
# so they run on their own pool, sized to the detector's own concurrency bound. A check
# past that bound queues here without holding any thread. The platform's parallel run uses
# this pool too, so the worker never runs more AI checks than the judge has model-call slots.
LLM_EVALUATE_EXECUTOR = ThreadPoolExecutor(
    max_workers=MAX_CONCURRENT_MODEL_CALLS, thread_name_prefix="insight-alert-llm-evaluate"
)
