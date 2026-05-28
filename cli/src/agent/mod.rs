//! Agent-first API access: a generic CLI surface over the full PostHog API,
//! driven by a declarative manifest generated from the same OpenAPI → MCP
//! pipeline. Phase 0 spike — see AGENTIC_CLI_PLAN.md.

pub mod command;
pub mod interpreter;
pub mod manifest;
