import type {
  McpAuthType,
  McpServerInstallation,
} from "@posthog/api-client/types";

interface OAuthRedirect {
  redirect_url: string;
}

type InstallResult = McpServerInstallation | OAuthRedirect;

export interface InstallFlowClient {
  installMcpTemplate(options: {
    template_id: string;
    api_key?: string;
    install_source?: "posthog" | "posthog-code";
    posthog_code_callback_url?: string;
  }): Promise<InstallResult>;
  installCustomMcpServer(options: {
    name: string;
    url: string;
    description?: string;
    auth_type: McpAuthType;
    api_key?: string;
    client_id?: string;
    client_secret?: string;
    install_source?: "posthog" | "posthog-code";
    posthog_code_callback_url?: string;
  }): Promise<InstallResult>;
  authorizeMcpInstallation(options: {
    installation_id: string;
    install_source?: "posthog" | "posthog-code";
    posthog_code_callback_url?: string;
  }): Promise<OAuthRedirect>;
}

export interface IOAuthCallback {
  getCallbackUrl(): Promise<{ callbackUrl: string }>;
  openAndWaitForCallback(args: {
    redirectUrl: string;
  }): Promise<OAuthCallbackResult>;
}

export interface OAuthCallbackResult {
  success?: boolean;
  error?: string;
}

const INSTALL_SOURCE = "posthog-code" as const;

function hasRedirect(data: InstallResult): data is OAuthRedirect {
  return "redirect_url" in data && !!data.redirect_url;
}

export async function installTemplateWithOAuth(
  client: InstallFlowClient,
  oauth: IOAuthCallback,
  vars: { template_id: string; api_key?: string },
): Promise<OAuthCallbackResult> {
  const { callbackUrl } = await oauth.getCallbackUrl();
  const data = await client.installMcpTemplate({
    ...vars,
    install_source: INSTALL_SOURCE,
    posthog_code_callback_url: callbackUrl,
  });
  if (hasRedirect(data)) {
    return oauth.openAndWaitForCallback({ redirectUrl: data.redirect_url });
  }
  return { success: true };
}

export async function installCustomWithOAuth(
  client: InstallFlowClient,
  oauth: IOAuthCallback,
  vars: {
    name: string;
    url: string;
    description: string;
    auth_type: McpAuthType;
    api_key?: string;
    client_id?: string;
    client_secret?: string;
  },
): Promise<OAuthCallbackResult> {
  const { callbackUrl } = await oauth.getCallbackUrl();
  const data = await client.installCustomMcpServer({
    ...vars,
    install_source: INSTALL_SOURCE,
    posthog_code_callback_url: callbackUrl,
  });
  if (hasRedirect(data)) {
    return oauth.openAndWaitForCallback({ redirectUrl: data.redirect_url });
  }
  return { success: true };
}

export async function reauthorizeWithOAuth(
  client: InstallFlowClient,
  oauth: IOAuthCallback,
  installationId: string,
): Promise<OAuthCallbackResult> {
  const { callbackUrl } = await oauth.getCallbackUrl();
  const data = await client.authorizeMcpInstallation({
    installation_id: installationId,
    install_source: INSTALL_SOURCE,
    posthog_code_callback_url: callbackUrl,
  });
  return oauth.openAndWaitForCallback({ redirectUrl: data.redirect_url });
}
