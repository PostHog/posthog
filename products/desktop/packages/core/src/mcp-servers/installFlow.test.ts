import type { McpServerInstallation } from "@posthog/api-client/types";
import { describe, expect, it, vi } from "vitest";
import {
  type InstallFlowClient,
  type IOAuthCallback,
  installCustomWithOAuth,
  installTemplateWithOAuth,
  reauthorizeWithOAuth,
} from "./installFlow";

function makeOAuth(
  openResult: { success?: boolean; error?: string } = { success: true },
): IOAuthCallback {
  return {
    getCallbackUrl: vi.fn().mockResolvedValue({ callbackUrl: "cb://here" }),
    openAndWaitForCallback: vi.fn().mockResolvedValue(openResult),
  };
}

const installedInstallation = {
  id: "inst-1",
} as McpServerInstallation;

describe("installTemplateWithOAuth", () => {
  it("builds the request with install_source + callback url and returns success when no redirect", async () => {
    const oauth = makeOAuth();
    const client: InstallFlowClient = {
      installMcpTemplate: vi.fn().mockResolvedValue(installedInstallation),
      installCustomMcpServer: vi.fn(),
      authorizeMcpInstallation: vi.fn(),
    };

    const result = await installTemplateWithOAuth(client, oauth, {
      template_id: "tpl-1",
      api_key: "k",
    });

    expect(client.installMcpTemplate).toHaveBeenCalledWith({
      template_id: "tpl-1",
      api_key: "k",
      install_source: "posthog-code",
      posthog_code_callback_url: "cb://here",
    });
    expect(oauth.openAndWaitForCallback).not.toHaveBeenCalled();
    expect(result).toEqual({ success: true });
  });

  it("opens and waits when the response carries a redirect_url", async () => {
    const oauth = makeOAuth({ success: true });
    const client: InstallFlowClient = {
      installMcpTemplate: vi
        .fn()
        .mockResolvedValue({ redirect_url: "https://auth" }),
      installCustomMcpServer: vi.fn(),
      authorizeMcpInstallation: vi.fn(),
    };

    const result = await installTemplateWithOAuth(client, oauth, {
      template_id: "tpl-1",
    });

    expect(oauth.openAndWaitForCallback).toHaveBeenCalledWith({
      redirectUrl: "https://auth",
    });
    expect(result).toEqual({ success: true });
  });
});

describe("installCustomWithOAuth", () => {
  it("forwards the custom payload and branches on redirect_url", async () => {
    const oauth = makeOAuth({ error: "denied" });
    const client: InstallFlowClient = {
      installMcpTemplate: vi.fn(),
      installCustomMcpServer: vi
        .fn()
        .mockResolvedValue({ redirect_url: "https://auth" }),
      authorizeMcpInstallation: vi.fn(),
    };

    const result = await installCustomWithOAuth(client, oauth, {
      name: "N",
      url: "https://x",
      description: "d",
      auth_type: "oauth",
    });

    expect(client.installCustomMcpServer).toHaveBeenCalledWith({
      name: "N",
      url: "https://x",
      description: "d",
      auth_type: "oauth",
      install_source: "posthog-code",
      posthog_code_callback_url: "cb://here",
    });
    expect(result).toEqual({ error: "denied" });
  });
});

describe("reauthorizeWithOAuth", () => {
  it("authorizes then opens the redirect", async () => {
    const oauth = makeOAuth();
    const client: InstallFlowClient = {
      installMcpTemplate: vi.fn(),
      installCustomMcpServer: vi.fn(),
      authorizeMcpInstallation: vi
        .fn()
        .mockResolvedValue({ redirect_url: "https://reauth" }),
    };

    const result = await reauthorizeWithOAuth(client, oauth, "inst-1");

    expect(client.authorizeMcpInstallation).toHaveBeenCalledWith({
      installation_id: "inst-1",
      install_source: "posthog-code",
      posthog_code_callback_url: "cb://here",
    });
    expect(oauth.openAndWaitForCallback).toHaveBeenCalledWith({
      redirectUrl: "https://reauth",
    });
    expect(result).toEqual({ success: true });
  });
});
