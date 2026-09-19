import type { ServiceContainer } from "@posthog/di/container";
import { ServiceProvider } from "@posthog/di/react";
import { CLAUDE_SUBSCRIPTION_TOKEN_SETTINGS } from "@posthog/ui/features/settings/claudeSubscriptionTokenSettings";
import { Theme } from "@radix-ui/themes";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { cloneElement } from "react";
import { describe, expect, it, vi } from "vitest";
import { BillingChip } from "./BillingChip";

const useAdapterSubscription = vi.hoisted(() => vi.fn());
vi.mock(
  "@posthog/ui/features/settings/adapterSubscription",
  async (importOriginal) => {
    const actual =
      await importOriginal<
        typeof import("@posthog/ui/features/settings/adapterSubscription")
      >();
    return { ...actual, useAdapterSubscription };
  },
);

// Base UI tooltips never open under jsdom's zero layout, so render their
// content unconditionally and assert on it directly (see the
// ReasoningLevelSelector tests for the same trick).
vi.mock("@posthog/quill", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@posthog/quill")>();
  const passthrough = ({ children }: { children: React.ReactNode }) => children;
  const renderPassthrough = ({
    children,
    render,
  }: {
    children?: React.ReactNode;
    render?: React.ReactElement;
  }) =>
    render && children
      ? cloneElement(render, undefined, children)
      : (render ?? children);
  return {
    ...actual,
    TooltipProvider: passthrough,
    Tooltip: passthrough,
    TooltipTrigger: renderPassthrough,
    TooltipContent: passthrough,
  };
});

const tokenStore = { has: vi.fn(), save: vi.fn(), clear: vi.fn() };

function renderChip(
  workspaceMode: "local" | "cloud",
  tokenSaved = true,
): ReturnType<typeof render> {
  tokenStore.has.mockResolvedValue(tokenSaved);
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
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        <Theme>
          <BillingChip adapter="claude" workspaceMode={workspaceMode} />
        </Theme>
      </QueryClientProvider>
    </ServiceProvider>,
  );
}

function subscriptionState(
  overrides?: Partial<{
    flagEnabled: boolean;
    subscriptionOn: boolean;
    loggedIn: boolean;
    cloudFlagEnabled: boolean;
    cloudSubscriptionOn: boolean;
  }>,
) {
  const base = {
    flagEnabled: true,
    subscriptionOn: true,
    loggedIn: true,
    setSubscriptionOn: () => {},
    setCloudSubscriptionOn: () => {},
    ...overrides,
  };
  // Mirror the real hook: the login state drives both the status payload and
  // whether the pick still needs a connection.
  const loginState = base.loggedIn ? "logged-in" : ("logged-out" as const);
  return {
    ...base,
    loginState,
    status: { loginState },
    needsConnection: base.subscriptionOn && !base.loggedIn,
  };
}

describe("BillingChip", () => {
  it.each([
    [
      "the provider plan once the login is confirmed",
      { subscriptionOn: true, loggedIn: true },
      "local",
      "Anthropic",
      "This run bills to your Anthropic plan.",
    ],
    [
      "PostHog while the provider pick has no login behind it",
      { subscriptionOn: true, loggedIn: false },
      "local",
      "PostHog",
      "This run bills to PostHog. Log in to Claude Code to use Anthropic billing.",
    ],
    [
      "PostHog for a cloud task that cannot use the provider plan",
      { subscriptionOn: true, loggedIn: true },
      "cloud",
      "PostHog",
      "This run bills to PostHog. Claude plan billing is unavailable for cloud tasks. Try again later.",
    ],
    [
      "PostHog without a cloud reason where cloud plan billing is offered",
      { subscriptionOn: true, loggedIn: true, cloudFlagEnabled: true },
      "cloud",
      "PostHog",
      "This run bills to PostHog.",
    ],
    [
      "the cloud pick as unavailable once the cloud flag is off",
      { cloudSubscriptionOn: true },
      "cloud",
      "Unavailable",
      "Claude plan billing is unavailable for cloud tasks. Try again later.",
    ],
  ] as const)(
    "names %s",
    async (_case, overrides, workspaceMode, label, hint) => {
      useAdapterSubscription.mockReturnValue(subscriptionState(overrides));
      renderChip(workspaceMode);

      expect(
        await screen.findByRole("button", { name: `Billing: ${label}` }),
      ).toHaveTextContent(label);
      expect(screen.getByText(hint)).toBeInTheDocument();
    },
  );

  it("names the cloud pick as unavailable while no token is saved", async () => {
    // The run needs a saved token that the access resolver never reads, so
    // without this the chip would promise a plan task creation refuses.
    useAdapterSubscription.mockReturnValue(
      subscriptionState({ cloudFlagEnabled: true, cloudSubscriptionOn: true }),
    );
    renderChip("cloud", false);

    expect(
      await screen.findByRole("button", { name: "Billing: Unavailable" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Cloud tasks on your Anthropic plan need a saved Claude token. Add one in Settings, or select PostHog.",
      ),
    ).toBeInTheDocument();
  });

  it("names the cloud pick as the provider plan once a token is saved", async () => {
    useAdapterSubscription.mockReturnValue(
      subscriptionState({ cloudFlagEnabled: true, cloudSubscriptionOn: true }),
    );
    renderChip("cloud", true);

    expect(
      await screen.findByRole("button", { name: "Billing: Anthropic" }),
    ).toBeInTheDocument();
  });

  it("stays hidden while the billing pick is unavailable", () => {
    useAdapterSubscription.mockReturnValue(
      subscriptionState({ flagEnabled: false }),
    );
    renderChip("local");

    expect(screen.queryByRole("button", { name: /^Billing/ })).toBeNull();
  });

  it("opens the same billing pick the model menu carries", async () => {
    useAdapterSubscription.mockReturnValue(subscriptionState());
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    renderChip("local");

    await user.click(screen.getByRole("button", { name: /^Billing/ }));

    expect(
      await screen.findByRole("menuitemradio", { name: "Anthropic" }),
    ).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("menuitemradio", { name: "PostHog" })).toBeTruthy();
  });
});
