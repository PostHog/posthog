import { Theme } from "@radix-ui/themes";
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
  ] as const)("names %s", (_case, overrides, workspaceMode, label, hint) => {
    useAdapterSubscription.mockReturnValue(subscriptionState(overrides));
    render(
      <Theme>
        <BillingChip adapter="claude" workspaceMode={workspaceMode} />
      </Theme>,
    );

    expect(screen.getByRole("button", { name: "Billing" })).toHaveTextContent(
      label,
    );
    expect(screen.getByText(hint)).toBeInTheDocument();
  });

  it("stays hidden while the billing pick is unavailable", () => {
    useAdapterSubscription.mockReturnValue(
      subscriptionState({ flagEnabled: false }),
    );
    render(
      <Theme>
        <BillingChip adapter="claude" workspaceMode="local" />
      </Theme>,
    );

    expect(screen.queryByRole("button", { name: "Billing" })).toBeNull();
  });

  it("opens the same billing pick the model menu carries", async () => {
    useAdapterSubscription.mockReturnValue(subscriptionState());
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    render(
      <Theme>
        <BillingChip adapter="claude" workspaceMode="local" />
      </Theme>,
    );

    await user.click(screen.getByRole("button", { name: "Billing" }));

    expect(
      await screen.findByRole("menuitemradio", { name: "Anthropic" }),
    ).toHaveAttribute("aria-checked", "true");
    expect(screen.getByRole("menuitemradio", { name: "PostHog" })).toBeTruthy();
  });
});
