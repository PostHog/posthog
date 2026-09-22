import type { FetchLike } from "@posthog/core/auth/auth";
import { net } from "electron";

/**
 * Fetch over Chromium's network stack. Unlike Node's undici (`globalThis.
 * fetch`), it honors system proxies and VPN routing, which undici
 * intermittently fails against ("fetch failed").
 */
export const electronNetFetch: FetchLike = (input, init) =>
  net.fetch(input, init);
