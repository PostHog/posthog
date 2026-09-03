import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { PrRefChip, type PrRefDetails } from "./PrRefChip";

const LOADED: PrRefDetails = {
  state: "closed",
  merged: true,
  draft: false,
  title: "Show pull request status in sessions",
  author: "octocat",
  isLoading: false,
  ciStatus: "success",
  isCiLoading: false,
};

describe("PrRefChip", () => {
  const href = "https://github.com/PostHog/posthog/pull/23985";

  async function hoverChip(): Promise<void> {
    const link = screen.getByText("PostHog/posthog#23985").closest("a");
    expect(link).not.toBeNull();
    await userEvent.hover(link as HTMLAnchorElement);
  }

  it("shows lifecycle, creator, and CI details for a pull request", async () => {
    render(
      <PrRefChip href={href} details={LOADED}>
        PostHog/posthog#23985
      </PrRefChip>,
    );

    expect(screen.getByRole("img", { name: "Merged" })).toBeInTheDocument();

    await hoverChip();

    expect(
      await screen.findByText("Show pull request status in sessions"),
    ).toBeInTheDocument();
    expect(screen.getByText("Created by @octocat")).toBeInTheDocument();
    expect(screen.getByText("CI passed")).toBeInTheDocument();
  });

  it("names the loading state while details are on the way", async () => {
    render(
      <PrRefChip
        href={href}
        details={{
          state: null,
          merged: false,
          draft: false,
          title: null,
          author: null,
          isLoading: true,
          ciStatus: null,
          isCiLoading: true,
        }}
      >
        PostHog/posthog#23985
      </PrRefChip>,
    );

    expect(
      screen.getByRole("img", { name: "Loading pull request status" }),
    ).toBeInTheDocument();

    await hoverChip();

    expect(screen.queryByText("CI passed")).not.toBeInTheDocument();
  });
});
