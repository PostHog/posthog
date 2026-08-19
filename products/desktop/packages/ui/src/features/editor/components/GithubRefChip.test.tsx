import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { GITHUB_REF_URL_ATTR, GithubRefChip } from "./GithubRefChip";

describe("GithubRefChip", () => {
  it("exposes its URL as a DOM attribute so the context menu can copy it", () => {
    const href = "https://github.com/PostHog/posthog/pull/23985";
    const { container } = render(
      <GithubRefChip href={href} kind="pr">
        PostHog/posthog#23985
      </GithubRefChip>,
    );

    const carrier = container.querySelector(`[${GITHUB_REF_URL_ATTR}]`);
    expect(carrier).not.toBeNull();
    expect(carrier?.getAttribute(GITHUB_REF_URL_ATTR)).toBe(href);
  });

  it("lets a nested right-click target resolve the URL via closest()", () => {
    const href = "https://github.com/PostHog/posthog/issues/42";
    render(
      <GithubRefChip href={href} kind="issue">
        PostHog/posthog#42
      </GithubRefChip>,
    );

    const label = screen.getByText("PostHog/posthog#42");
    expect(
      label
        .closest(`[${GITHUB_REF_URL_ATTR}]`)
        ?.getAttribute(GITHUB_REF_URL_ATTR),
    ).toBe(href);
  });

  it("shows lifecycle, creator, and CI details for a pull request", async () => {
    const href = "https://github.com/PostHog/posthog/pull/23985";
    render(
      <GithubRefChip
        href={href}
        kind="pr"
        prDetails={{
          state: "closed",
          merged: true,
          draft: false,
          title: "Show pull request status in sessions",
          author: "octocat",
          ciStatus: "success",
          isLoading: false,
        }}
      >
        PostHog/posthog#23985
      </GithubRefChip>,
    );

    expect(screen.getByRole("img", { name: "Merged" })).toBeInTheDocument();

    const link = screen.getByText("PostHog/posthog#23985").closest("a");
    expect(link).not.toBeNull();
    await userEvent.hover(link as HTMLAnchorElement);

    expect(
      await screen.findByText("Show pull request status in sessions"),
    ).toBeInTheDocument();
    expect(screen.getByText("Created by @octocat")).toBeInTheDocument();
    expect(screen.getByText("CI passed")).toBeInTheDocument();
  });
});
