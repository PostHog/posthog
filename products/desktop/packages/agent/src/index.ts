export { isNotification, POSTHOG_NOTIFICATIONS } from "./acp-extensions";
export {
  getMcpToolMetadata,
  isMcpToolReadOnly,
  type McpToolMetadata,
} from "./adapters/claude/mcp/tool-metadata";
export { detectRtkBinary } from "./adapters/claude/session/rtk";
export type { PostHogProductId } from "./posthog-products";
