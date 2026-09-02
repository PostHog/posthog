import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

const usePrDetailsMock = vi.hoisted(() => vi.fn());
const usePrChecksMock = vi.hoisted(() => vi.fn());

vi.mock("@posthog/ui/features/git-interaction/usePrDetails", () => ({
  usePrDetails: usePrDetailsMock,
}));

vi.mock("@posthog/ui/features/pr-review/usePrChecks", () => ({
  usePrChecks: usePrChecksMock,
}));

import { GithubPrRefChip } from "./GithubPrRefChip";

describe("GithubPrRefChip", () => {
  it("refreshes lifecycle state and loads CI when its tooltip opens", async () => {
    const href = "https://github.com/PostHog/posthog/pull/23985";
    usePrDetailsMock.mockReturnValue({
      meta: {
        state: "open",
        merged: false,
        draft: true,
        headRefName: "posthog/status-chip",
        title: "Show pull request status in sessions",
        author: "octocat",
        isLoading: false,
      },
      commentThreads: new Map(),
      commentsLoading: false,
    });
    usePrChecksMock.mockReturnValue({
      data: [
        {
          name: "Desktop CI",
          bucket: "pass",
          link: null,
          workflow: null,
          description: null,
        },
      ],
      isLoading: false,
    });

    render(
      <GithubPrRefChip href={href}>PostHog/posthog#23985</GithubPrRefChip>,
    );

    expect(screen.getByRole("img", { name: "Draft" })).toBeInTheDocument();
    expect(usePrDetailsMock).toHaveBeenCalledWith(href, {
      refetchInterval: 30_000,
    });
    expect(usePrChecksMock).toHaveBeenCalledWith(null);

    const link = screen.getByText("PostHog/posthog#23985").closest("a");
    expect(link).not.toBeNull();
    await userEvent.hover(link as HTMLAnchorElement);

    expect(await screen.findByText("CI passed")).toBeInTheDocument();
    expect(usePrChecksMock).toHaveBeenCalledWith(href);
  });
});
