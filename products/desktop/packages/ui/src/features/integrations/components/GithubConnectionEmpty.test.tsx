import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { GithubConnectionEmpty } from "./GithubConnectionEmpty";

vi.mock("@posthog/ui/utils/browser", () => ({
  openUrlInBrowser: vi.fn(),
}));

describe("GithubConnectionEmpty", () => {
  it.each([
    { showLearnMore: true, expected: true },
    { showLearnMore: false, expected: false },
  ])(
    "sets Learn more visibility to $expected",
    ({ showLearnMore, expected }) => {
      render(
        <GithubConnectionEmpty
          connected={false}
          description="Connect GitHub to continue."
          showLearnMore={showLearnMore}
          title="Connect GitHub"
        >
          <span>Connection action</span>
        </GithubConnectionEmpty>,
      );

      expect(screen.getByText("Connection action")).toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: "Learn more" }) !== null,
      ).toBe(expected);
    },
  );
});
