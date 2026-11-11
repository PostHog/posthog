# @posthog/ingestion-ai-research

The AI research team's session replay pipelines and servers: the ML mirror, image fetch and image scrub, the anonymizer and the v4 recorder sinks. They are built on `@posthog/ingestion`'s session replay pipeline and `@posthog/replay-storage`, and on the native addons built from `rust/replay-anonymizer-node` and `rust/ai-research/replay-core-v4-node`, all consumed by workspace path. The package is its own merge queue lane and ships as its own image (`ingestion-ai-research-node`).
