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

  it("keeps the whole pull request number outside the truncating span", () => {
    const { container } = render(
      <GithubRefChip
        href="https://github.com/PostHog/posthog/pull/123456789"
        kind="pr"
      >
        PostHog/posthog#123456789
      </GithubRefChip>,
    );

    const label = container.querySelector(".truncate");
    expect(label).toHaveTextContent("PostHog/posthog");
    expect(label).not.toHaveAttribute("dir");
    expect(label).toHaveStyle({
      maxWidth: "min(16rem, calc(100% - 1rem - 10ch))",
    });
    const number = screen.getByText("#123456789");
    expect(number).toHaveClass("shrink-0");
    expect(number.parentElement).not.toHaveAttribute("dir");
  });

  it("clips the chip so a long preserved number cannot paint past the edge", () => {
    const { container } = render(
      <GithubRefChip
        href="https://github.com/PostHog/posthog/pull/123456789"
        kind="pr"
      >
        PostHog/posthog#123456789
      </GithubRefChip>,
    );

    expect(container.querySelector("a")).toHaveClass("overflow-hidden");
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
