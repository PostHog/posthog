export const HARNESS_EXTENSION_ENTRYPOINTS = {
  "hog-branding": "hog-branding/index",
  "posthog-provider": "posthog-provider/index",
  "product-engineer": "product-engineer/index",
  "background-jobs": "background-jobs/index",
  orchestration: "orchestration/index",
  "web-access": "web-access/index",
  mcp: "mcp/index",
  "posthog-mcp-policy": "posthog-mcp-policy/index",
  rtk: "rtk/index",
} as const;

export type HarnessExtensionName = keyof typeof HARNESS_EXTENSION_ENTRYPOINTS;
