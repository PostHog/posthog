import { render, screen } from "@testing-library/react";
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

  it("truncates a pull request label from the start so its number survives", () => {
    render(
      <GithubRefChip
        href="https://github.com/PostHog/posthog/pull/123456789"
        kind="pr"
      >
        PostHog/posthog#123456789
      </GithubRefChip>,
    );

    const label = screen.getByText("PostHog/posthog#123456789");
    expect(label).toHaveAttribute("dir", "ltr");
    expect(label.parentElement).toHaveAttribute("dir", "rtl");
    expect(label.parentElement).toHaveClass("truncate");
  });

  it("leaves a label that puts its number first alone", () => {
    render(
      <GithubRefChip
        href="https://github.com/PostHog/posthog/pull/42"
        kind="pr"
      >
        #42 - Fix the sign-up redirect
      </GithubRefChip>,
    );

    expect(
      screen.getByText("#42 - Fix the sign-up redirect"),
    ).not.toHaveAttribute("dir");
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
});
