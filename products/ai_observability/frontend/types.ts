// The compat message/trace types moved to the shared @posthog/llm-normalizer package so
// services/mcp can use them without importing products/. Re-exported here so the many
// in-product consumers keep their import path.
export * from '@posthog/llm-normalizer/types'
