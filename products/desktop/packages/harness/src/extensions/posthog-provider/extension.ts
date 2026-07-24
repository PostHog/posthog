import type {
  ExtensionAPI,
  ExtensionFactory,
} from "@earendil-works/pi-coding-agent";
import {
  POSTHOG_PROVIDER_NAME,
  type PosthogProviderOptions,
  resolvePosthogProvider,
} from "./provider";

export function createPosthogProviderExtension(
  options: PosthogProviderOptions = {},
): ExtensionFactory {
  return async (pi: ExtensionAPI) => {
    pi.registerProvider(
      POSTHOG_PROVIDER_NAME,
      await resolvePosthogProvider(options),
    );
  };
}

export default function posthogProvider(
  pi: ExtensionAPI,
): void | Promise<void> {
  return createPosthogProviderExtension()(pi);
}
