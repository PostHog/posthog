import { ClaudeIntegrationUnavailableError } from "@posthog/api-client/posthog-client";
import type { ServiceContainer } from "@posthog/di/container";
import { ServiceProvider } from "@posthog/di/react";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { CLAUDE_SUBSCRIPTION_TOKEN_SETTINGS } from "@posthog/ui/features/settings/claudeSubscriptionTokenSettings";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const {
  tokenStore,
  client,
  track,
  setClaudeCloudSubscriptionOn,
  toast,
  VALID_TOKEN,
} = vi.hoisted(() => ({
  VALID_TOKEN: "sk-ant-oat01-fake-test-token-00000000000000",
  tokenStore: {
    save: vi.fn(),
    clear: vi.fn(),
    has: vi.fn(),
  },
  client: {
    getClaudeUserIntegration: vi.fn(),
    connectClaudeUserIntegration: vi.fn(),
    disconnectClaudeUserIntegration: vi.fn(),
  },
  track: vi.fn(),
  setClaudeCloudSubscriptionOn: vi.fn(),
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
  },
}));

vi.mock("@posthog/ui/features/settings/settingsStore", () => ({
  useSettingsStore: (selector: (s: unknown) => unknown) =>
    selector({ setClaudeCloudSubscriptionOn }),
}));

vi.mock("@posthog/ui/features/auth/authClient", () => ({
  useOptionalAuthenticatedClient: () => client,
}));

vi.mock("@posthog/ui/primitives/toast", () => ({ toast }));

vi.mock("@posthog/ui/shell/analytics", () => ({ track }));

vi.mock("./ClaudeAuthTerminalDialog", () => ({
  ClaudeAuthTerminalDialog: ({
    onSaveToken,
    savingToken,
  }: {
    onSaveToken: (token: string) => void;
    savingToken: boolean;
  }) => (
    <div role="dialog">
      <button
        type="button"
        disabled={savingToken}
        onClick={() => onSaveToken(VALID_TOKEN)}
      >
        Save found token
      </button>
    </div>
  ),
}));

import { ClaudeCloudTokenSection } from "./ClaudeCloudTokenSection";

const DAY_MS = 24 * 60 * 60 * 1000;

function integration(
  status: "connected" | "reauth_required" | "not_connected",
  expiresInMs = 300 * DAY_MS,
) {
  return {
    status,
    connected_at: status === "connected" ? "2026-01-01T00:00:00Z" : null,
    expires_at:
      status === "connected"
        ? new Date(Date.now() + expiresInMs).toISOString()
        : null,
  };
}

function renderSection(cloudSubscriptionOn = false): ReturnType<typeof render> {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const container: ServiceContainer = {
    get: () => tokenStore,
    getAll: () => [],
    isBound: (token) => token === CLAUDE_SUBSCRIPTION_TOKEN_SETTINGS,
    bind: () => {
      throw new Error("Test services are fixed");
    },
  };
  return render(
    <ServiceProvider container={container}>
      <QueryClientProvider client={queryClient}>
        <ClaudeCloudTokenSection cloudSubscriptionOn={cloudSubscriptionOn} />
      </QueryClientProvider>
    </ServiceProvider>,
  );
}

describe("ClaudeCloudTokenSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    tokenStore.has.mockResolvedValue(false);
    tokenStore.clear.mockResolvedValue(undefined);
    tokenStore.save.mockResolvedValue(undefined);
    client.getClaudeUserIntegration.mockResolvedValue(
      integration("not_connected"),
    );
    client.connectClaudeUserIntegration.mockResolvedValue(
      integration("connected"),
    );
    client.disconnectClaudeUserIntegration.mockResolvedValue(undefined);
  });

  it("shows the validation message and does not send a malformed token", async () => {
    const user = userEvent.setup();
    renderSection();

    const input = await screen.findByLabelText("Claude setup token");
    await user.type(input, "not-a-claude-token");
    await user.click(screen.getByRole("button", { name: "Save token" }));

    const error = await screen.findByRole("alert");
    expect(error).toHaveTextContent(
      "Paste the full token from the terminal. It starts with sk-ant-oat01-.",
    );
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAttribute("aria-describedby", error.id);
    expect(toast.error).not.toHaveBeenCalled();
    expect(client.connectClaudeUserIntegration).not.toHaveBeenCalled();
    await user.clear(input);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(input).not.toHaveAttribute("aria-invalid");
  });

  it.each([
    { replacing: false, pasted: VALID_TOKEN },
    { replacing: true, pasted: VALID_TOKEN },
    {
      replacing: false,
      pasted: "  sk-ant-oat01-fake-test-\n  token-00000000000000\n",
    },
    {
      replacing: true,
      pasted: "\tsk-ant-oat01-fake-\r\n  test-token-\r\n  00000000000000 ",
    },
    { replacing: false, pasted: null },
    { replacing: true, pasted: null },
  ])(
    "sends a pasted or terminal token to PostHog and then keeps a local copy for the relay (case %#)",
    async ({ replacing, pasted }) => {
      const user = userEvent.setup();
      client.getClaudeUserIntegration.mockResolvedValue(
        integration(replacing ? "connected" : "not_connected"),
      );
      renderSection();
      if (replacing) {
        await user.click(
          await screen.findByRole("button", { name: "Replace token" }),
        );
      }

      const input = await screen.findByLabelText("Claude setup token");
      if (pasted === null) {
        await user.click(screen.getByRole("button", { name: "Create token" }));
        await user.click(
          screen.getByRole("button", { name: "Save found token" }),
        );
      } else {
        await user.click(input);
        await user.paste(pasted);
        await user.click(screen.getByRole("button", { name: "Save token" }));
      }

      expect(await screen.findByText("Token saved")).toBeInTheDocument();
      expect(screen.queryByRole("dialog")).toBeNull();
      expect(toast.success).toHaveBeenCalledWith("Token saved");
      expect(
        screen.getByText(/PostHog keeps your Claude token/),
      ).toBeInTheDocument();
      expect(
        client.connectClaudeUserIntegration,
      ).toHaveBeenCalledExactlyOnceWith(VALID_TOKEN);
      expect(tokenStore.save).toHaveBeenCalledExactlyOnceWith(VALID_TOKEN);
      expect(tokenStore.clear).not.toHaveBeenCalled();
      expect(
        client.connectClaudeUserIntegration.mock.invocationCallOrder[0],
      ).toBeLessThan(tokenStore.save.mock.invocationCallOrder[0]);
      expect(track).toHaveBeenCalledWith(
        ANALYTICS_EVENTS.CLAUDE_CLOUD_TOKEN_SAVED,
      );
    },
  );

  it("keeps the token on this device when PostHog cannot store it yet", async () => {
    const user = userEvent.setup();
    client.getClaudeUserIntegration.mockResolvedValue(null);
    client.connectClaudeUserIntegration.mockRejectedValue(
      new ClaudeIntegrationUnavailableError(),
    );
    tokenStore.save.mockResolvedValue(undefined);
    renderSection();

    expect(
      await screen.findByText(
        "Keep Desktop open to start or resume. Compute is billed separately.",
      ),
    ).toBeInTheDocument();
    await user.click(await screen.findByLabelText("Claude setup token"));
    await user.paste(VALID_TOKEN);
    await user.click(screen.getByRole("button", { name: "Save token" }));

    expect(await screen.findByText("Token saved")).toBeInTheDocument();
    expect(tokenStore.save).toHaveBeenCalledExactlyOnceWith(VALID_TOKEN);
    expect(tokenStore.clear).not.toHaveBeenCalled();
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("keeps the local token when PostHog rejects the new one", async () => {
    const user = userEvent.setup();
    tokenStore.has.mockResolvedValue(true);
    client.connectClaudeUserIntegration.mockRejectedValue(
      new Error("Paste the full Claude token."),
    );
    renderSection();

    await user.click(await screen.findByLabelText("Claude setup token"));
    await user.paste(VALID_TOKEN);
    await user.click(screen.getByRole("button", { name: "Save token" }));

    await vi.waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Cannot save the token.", {
        description: "Paste the full Claude token.",
      }),
    );
    expect(tokenStore.clear).not.toHaveBeenCalled();
    expect(tokenStore.save).not.toHaveBeenCalled();
    expect(track).not.toHaveBeenCalled();
  });

  it("removes the token from PostHog and from this device", async () => {
    const user = userEvent.setup();
    client.getClaudeUserIntegration.mockResolvedValue(integration("connected"));
    renderSection();

    expect(await screen.findByText("Token saved")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Replace token" }));
    await user.type(screen.getByLabelText("Claude setup token"), "draft-token");
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByText("Token saved")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Remove token" }));
    expect(client.disconnectClaudeUserIntegration).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Confirm removal" }));

    await vi.waitFor(() =>
      expect(track).toHaveBeenCalledWith(
        ANALYTICS_EVENTS.CLAUDE_CLOUD_TOKEN_REMOVED,
      ),
    );
    expect(client.disconnectClaudeUserIntegration).toHaveBeenCalledOnce();
    expect(tokenStore.clear).toHaveBeenCalledOnce();
    expect(client.connectClaudeUserIntegration).not.toHaveBeenCalled();
  });

  it.each([
    [
      "reauth_required",
      false,
      "Claude does not accept this token. Create a new token, then paste it below.",
    ],
    [
      "not_connected",
      true,
      "Paste your token again so cloud tasks can run when Desktop is closed.",
    ],
  ] as const)(
    "asks for a new token when the server token is %s (local token: %s)",
    async (status, hasLocalToken, hint) => {
      client.getClaudeUserIntegration.mockResolvedValue(integration(status));
      tokenStore.has.mockResolvedValue(hasLocalToken);
      renderSection(true);

      expect(await screen.findByText(hint)).toBeInTheDocument();
      expect(screen.getByLabelText("Claude setup token")).toBeInTheDocument();
      expect(client.connectClaudeUserIntegration).not.toHaveBeenCalled();
    },
  );

  it("warns about an expiring token and offers a new token", async () => {
    const user = userEvent.setup();
    client.getClaudeUserIntegration.mockResolvedValue(
      integration("connected", 5 * DAY_MS - 60 * 60 * 1000),
    );
    renderSection(true);

    expect(
      await screen.findByText(
        "Your Claude token expires in about 5 days. Create a new token before this date.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/PostHog keeps your Claude token/),
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Create token" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("shows a retryable error when Desktop cannot read the local token", async () => {
    const user = userEvent.setup();
    client.getClaudeUserIntegration.mockResolvedValue(null);
    tokenStore.has
      .mockRejectedValueOnce(new Error("Key store locked."))
      .mockResolvedValue(true);
    renderSection(true);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Desktop cannot read the token on this device. Try again.",
    );
    expect(screen.queryByText("Token saved")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Token saved")).toBeInTheDocument();
  });

  it("shows a retryable error when PostHog cannot report the token status", async () => {
    const user = userEvent.setup();
    client.getClaudeUserIntegration.mockRejectedValueOnce(
      new Error("Network request failed."),
    );
    renderSection(true);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Cannot check your Claude token. Network request failed.",
    );
    expect(
      screen.queryByLabelText("Claude setup token"),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(/Compute is billed separately/),
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(
      await screen.findByLabelText("Claude setup token"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Save a token so cloud tasks can run when Desktop is closed. Compute is billed separately.",
      ),
    ).toBeInTheDocument();
  });
});
