import type {
  ExtensionAPI,
  ExtensionFactory,
} from "@earendil-works/pi-coding-agent";
import type { PosthogProviderOptions } from "../posthog-provider/provider";
import { createWebFetchTool } from "./web-fetch";
import { createWebSearchTool } from "./web-search";

export type WebAccessOptions = PosthogProviderOptions;

export function createWebAccessExtension(
  options: WebAccessOptions = {},
): ExtensionFactory {
  return (pi: ExtensionAPI) => {
    pi.registerTool(createWebSearchTool(options));
    pi.registerTool(createWebFetchTool(options));
  };
}

export default function webAccess(pi: ExtensionAPI): void | Promise<void> {
  return createWebAccessExtension()(pi);
}
