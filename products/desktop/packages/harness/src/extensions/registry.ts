import { fileURLToPath } from "node:url";
import type {
  ExtensionFactory,
  InlineExtension,
} from "@earendil-works/pi-coding-agent";
import type { HogBrandingOptions } from "./hog-branding/extension";
import { createHogBrandingExtension } from "./hog-branding/extension";
import type { McpConfig } from "./mcp/config";
import { createMcpExtension } from "./mcp/extension";
import type { PosthogMcpPolicyOptions } from "./posthog-mcp-policy/extension";
import { createPosthogMcpPolicyExtension } from "./posthog-mcp-policy/extension";
import { createPosthogProviderExtension } from "./posthog-provider/extension";
import type { PosthogProviderOptions } from "./posthog-provider/provider";
import { createProductEngineerExtension } from "./product-engineer/extension";
import { createWebAccessExtension } from "./web-access/extension";

export type HarnessExtensionOptions = PosthogProviderOptions &
  HogBrandingOptions &
  PosthogMcpPolicyOptions & {
    runtimeMcpServers?: McpConfig["mcpServers"];
  };

interface HarnessExtension {
  name: string;
  create: (options: HarnessExtensionOptions) => ExtensionFactory;
}

const EXTENSIONS: HarnessExtension[] = [
  { name: "hog-branding", create: createHogBrandingExtension },
  { name: "posthog-provider", create: createPosthogProviderExtension },
  { name: "product-engineer", create: () => createProductEngineerExtension() },
  { name: "web-access", create: createWebAccessExtension },
  {
    name: "mcp",
    create: (options) =>
      createMcpExtension({ runtimeServers: options.runtimeMcpServers }),
  },
  {
    name: "posthog-mcp-policy",
    create: createPosthogMcpPolicyExtension,
  },
];

export const HARNESS_EXTENSION_NAMES: readonly string[] = EXTENSIONS.map(
  (extension) => extension.name,
);

export interface HarnessExtensionFilesOptions {
  exclude?: string[];
}

/** Compiled extension entry points consumed by Pi's native CLI. */
export function harnessExtensionFiles(
  options: HarnessExtensionFilesOptions = {},
): string[] {
  const exclude = new Set(options.exclude ?? []);
  return HARNESS_EXTENSION_NAMES.filter((name) => !exclude.has(name)).map(
    (name) => fileURLToPath(new URL(`./${name}/index.js`, import.meta.url)),
  );
}

export function harnessExtensions(
  options: HarnessExtensionOptions = {},
): InlineExtension[] {
  return EXTENSIONS.map((extension) => ({
    name: extension.name,
    factory: extension.create(options),
  }));
}
