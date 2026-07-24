import * as Linking from "expo-linking";
import * as WebBrowser from "expo-web-browser";
import {
  authorizeMcpInstallation,
  installCustomMcpServer,
  installMcpTemplate,
} from "./api";
import type {
  InstallCustomMcpServerOptions,
  InstallMcpTemplateOptions,
  McpInstallResponse,
  McpServerInstallation,
} from "./types";
import { isOAuthRedirect } from "./types";

/** Custom URL scheme registered via app.json (`scheme: "posthog"`). The cloud
 *  bounces the OAuth redirect back to this URL once the provider completes
 *  auth, and `expo-linking` catches it on both iOS and Android. */
export const OAUTH_CALLBACK_URL = "posthog://mcp-oauth/callback";

const INSTALL_SOURCE = "posthog-code" as const;

/**
 * Open the cloud-provided redirect URL in the system browser and wait for the
 * user to complete the OAuth dance. Resolves once the cloud bounces the
 * callback back to `OAUTH_CALLBACK_URL`, or once the user dismisses the
 * browser without completing.
 */
async function waitForOAuthCallback(
  redirectUrl: string,
): Promise<"completed" | "cancelled"> {
  // `openAuthSessionAsync` automatically dismisses the browser sheet on the
  // first incoming deep link matching our scheme — handy for OAuth on both
  // iOS (ASWebAuthenticationSession) and Android (Custom Tabs).
  const result = await WebBrowser.openAuthSessionAsync(
    redirectUrl,
    OAUTH_CALLBACK_URL,
  );

  if (result.type === "success") return "completed";
  return "cancelled";
}

/**
 * Run the install flow for a marketplace template. If the cloud responds with
 * an OAuth redirect, take the user through it and resolve once they're back.
 */
export async function installTemplateWithOAuth(
  options: Omit<
    InstallMcpTemplateOptions,
    "install_source" | "posthog_code_callback_url"
  >,
): Promise<McpServerInstallation | "cancelled"> {
  const response: McpInstallResponse = await installMcpTemplate({
    ...options,
    install_source: INSTALL_SOURCE,
    posthog_code_callback_url: OAUTH_CALLBACK_URL,
  });

  if (!isOAuthRedirect(response)) return response;

  const outcome = await waitForOAuthCallback(response.redirect_url);
  if (outcome === "cancelled") return "cancelled";

  // Cloud has stored the refresh token on success — we don't get the
  // installation row back from the OAuth dance, so callers refetch the
  // installations list.
  return "cancelled";
}

/** Same as install-template, for custom servers. */
export async function installCustomWithOAuth(
  options: Omit<
    InstallCustomMcpServerOptions,
    "install_source" | "posthog_code_callback_url"
  >,
): Promise<McpServerInstallation | "cancelled"> {
  const response: McpInstallResponse = await installCustomMcpServer({
    ...options,
    install_source: INSTALL_SOURCE,
    posthog_code_callback_url: OAUTH_CALLBACK_URL,
  });

  if (!isOAuthRedirect(response)) return response;
  const outcome = await waitForOAuthCallback(response.redirect_url);
  return outcome === "cancelled" ? "cancelled" : "cancelled";
}

/**
 * Trigger a re-auth flow for an installation whose OAuth token has expired
 * (cloud sets `needs_reauth: true`). Opens the cloud's authorize endpoint,
 * which returns a redirect URL, then runs the same WebBrowser session.
 */
export async function reauthorizeInstallation(
  installationId: string,
): Promise<"completed" | "cancelled"> {
  const { redirect_url } = await authorizeMcpInstallation({
    installation_id: installationId,
    install_source: INSTALL_SOURCE,
    posthog_code_callback_url: OAUTH_CALLBACK_URL,
  });
  return waitForOAuthCallback(redirect_url);
}

/** Subscribe to deep-link events for the OAuth callback. Mainly useful when
 *  the WebBrowser session can't auto-dismiss for some reason. */
export function onOAuthCallback(handler: (url: string) => void): {
  remove(): void;
} {
  const subscription = Linking.addEventListener("url", ({ url }) => {
    if (url.startsWith(OAUTH_CALLBACK_URL)) handler(url);
  });
  return subscription;
}
