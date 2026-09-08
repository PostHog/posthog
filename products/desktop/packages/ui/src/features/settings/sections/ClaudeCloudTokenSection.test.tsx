import type { ServiceContainer } from "@posthog/di/container";
import { ServiceProvider } from "@posthog/di/react";
import { ANALYTICS_EVENTS } from "@posthog/shared";
import { CLAUDE_SUBSCRIPTION_TOKEN_SETTINGS } from "@posthog/ui/features/settings/claudeSubscriptionTokenSettings";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const { tokenStore, track, setClaudeCloudSubscriptionOn, toast, createToken } =
  vi.hoisted(() => ({
    tokenStore: {
      save: vi.fn(),
      clear: vi.fn(),
      has: vi.fn(),
    },
    track: vi.fn(),
    createToken: vi.fn(),
    setClaudeCloudSubscriptionOn: vi.fn(),
    toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
  }));

vi.mock("@posthog/ui/features/settings/settingsStore", () => ({
  useSettingsStore: (selector: (s: unknown) => unknown) =>
    selector({ setClaudeCloudSubscriptionOn }),
}));

vi.mock("@posthog/ui/primitives/toast", () => ({ toast }));

vi.mock("@posthog/ui/shell/analytics", () => ({ track }));

import { ClaudeCloudTokenSection } from "./ClaudeCloudTokenSection";

const VALID_TOKEN = "sk-ant-oat01-fake-test-token-00000000000000";

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
        <ClaudeCloudTokenSection
          cloudSubscriptionOn={cloudSubscriptionOn}
          onCreateToken={createToken}
        />
      </QueryClientProvider>
    </ServiceProvider>,
  );
}

describe("ClaudeCloudTokenSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    tokenStore.has.mockResolvedValue(false);
  });

  it("shows the validation message and does not save a malformed token", async () => {
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
    expect(tokenStore.save).not.toHaveBeenCalled();
    await user.clear(input);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(input).not.toHaveAttribute("aria-invalid");
  });

  it.each([false, true])(
    "saves a token without clearing the previous one (replacing: %s)",
    async (replacing) => {
      const user = userEvent.setup();
      tokenStore.save.mockResolvedValue(undefined);
      tokenStore.has.mockResolvedValue(replacing);
      renderSection();
      if (replacing) {
        await user.click(
          await screen.findByRole("button", { name: "Replace token" }),
        );
      }

      const input = await screen.findByLabelText("Claude setup token");
      await user.click(screen.getByRole("button", { name: "Create token" }));
      expect(createToken).toHaveBeenCalledTimes(1);
      await user.type(input, VALID_TOKEN);
      await user.click(screen.getByRole("button", { name: "Save token" }));

      expect(tokenStore.save).toHaveBeenCalledTimes(1);
      expect(tokenStore.save).toHaveBeenCalledWith(VALID_TOKEN);
      expect(tokenStore.clear).not.toHaveBeenCalled();
      expect(track).toHaveBeenCalledWith(
        ANALYTICS_EVENTS.CLAUDE_CLOUD_TOKEN_SAVED,
      );
      expect(await screen.findByText("Token saved")).toBeInTheDocument();
    },
  );

  it("shows the saved state and removes the token on demand", async () => {
    const user = userEvent.setup();
    tokenStore.has.mockResolvedValue(true);
    tokenStore.clear.mockResolvedValue(undefined);
    renderSection();

    expect(await screen.findByText("Token saved")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Replace token" }));
    await user.type(screen.getByLabelText("Claude setup token"), "draft-token");
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByText("Token saved")).toBeInTheDocument();
    expect(tokenStore.save).not.toHaveBeenCalled();
    expect(tokenStore.clear).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Remove token" }));
    expect(tokenStore.clear).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Confirm removal" }));
    expect(tokenStore.clear).toHaveBeenCalledTimes(1);
    expect(track).toHaveBeenCalledWith(
      ANALYTICS_EVENTS.CLAUDE_CLOUD_TOKEN_REMOVED,
    );
  });
  it("shows a retryable error instead of treating an unreadable token as missing", async () => {
    const user = userEvent.setup();
    tokenStore.has.mockRejectedValueOnce(new Error("storage unavailable"));
    renderSection(true);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Cannot check your token.",
    );
    expect(
      screen.queryByLabelText("Claude setup token"),
    ).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(
      await screen.findByLabelText("Claude setup token"),
    ).toBeInTheDocument();
  });
});
