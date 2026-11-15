// ── Detection API (replaces posthog-vscode tree-sitter service) ──

export { EXT_TO_LANG_ID } from "./languages.js";
export { setLogger } from "./log.js";

export type {
  ImportEdge,
  LocalWrapper,
  ParseContext,
} from "./types.js";
// ── Enricher API ──

export { PostHogEnricher } from "./enricher.js";
export { ParseResult } from "./parse-result.js";
export { PostHogApi } from "./posthog-api.js";
// ── Shared enrichment pipeline ──

export { enrichSource } from "./enrich-source.js";

// ── Serialisation (tRPC/IPC boundary) ──

export type { SerializedEnrichment } from "./serialize.js";
export { toSerializable } from "./serialize.js";
