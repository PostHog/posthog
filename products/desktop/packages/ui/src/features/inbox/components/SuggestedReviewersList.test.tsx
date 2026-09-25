import type { SuggestedReviewer } from "@posthog/shared/types";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SuggestedReviewersList } from "./SuggestedReviewersList";

function ungroupedReviewer(index: number): SuggestedReviewer {
  return {
    github_login: `dev-${index}`,
    github_name: `Dev ${index}`,
    relevant_commits: [],
    user: {
      id: index,
      uuid: `dev-${index}`,
      first_name: "Dev",
      last_name: `${index}`,
      email: `dev-${index}@example.com`,
    },
    explanation: `Owns area ${index}.`,
  };
}

describe("SuggestedReviewersList", () => {
  it("shows the shared reason before its indented reviewers and always shows remove controls", () => {
    const reason = "Maintains request handling.";
    const reviewers = [0, 1].map((index) => ({
      ...ungroupedReviewer(index),
      reason,
      explanation: reason,
    }));

    render(
      <SuggestedReviewersList
        reviewers={reviewers}
        disabled={false}
        onRemove={vi.fn()}
      />,
    );

    const reasonElement = screen.getByText(reason);
    const firstReviewer = screen.getByText("Dev 0");
    expect(
      reasonElement.compareDocumentPosition(firstReviewer) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(firstReviewer.closest(".pl-3")).toBeInTheDocument();
    expect(reasonElement.parentElement?.parentElement).not.toHaveClass(
      "border",
    );
    expect(screen.getAllByRole("button", { name: /^Remove / })).toHaveLength(2);
    expect(
      screen.getByRole("button", { name: "Remove Dev 0" }),
    ).not.toHaveClass("opacity-0");
  });

  it.each([
    [
      "a hover",
      async (user: ReturnType<typeof userEvent.setup>, badge: HTMLElement) => {
        await user.hover(badge);
      },
    ],
    [
      "keyboard focus",
      async (user: ReturnType<typeof userEvent.setup>, badge: HTMLElement) => {
        await user.tab();
        expect(badge).toHaveFocus();
      },
    ],
  ])(
    "reveals a scout name in the source tooltip on %s",
    async (_case, reveal) => {
      const user = userEvent.setup();
      const scoutName =
        "Infrastructure reliability and request processing ownership scout";
      const reviewer: SuggestedReviewer = {
        github_login: "solo",
        github_name: "Solo Scout",
        relevant_commits: [],
        user: {
          id: 1,
          uuid: "solo",
          first_name: "Solo",
          last_name: "Scout",
          email: "solo@example.com",
        },
        source_skill: "signals-scout-infrastructure-reliability",
        source_label: scoutName,
        explanation: "Maintains the request path.",
      };

      render(
        <SuggestedReviewersList reviewers={[reviewer]} disabled={false} />,
      );

      const badge = screen.getByText("Added by scout");
      expect(badge).toBeInTheDocument();
      expect(screen.queryByText(scoutName)).not.toBeInTheDocument();

      await reveal(user, badge);

      expect(await screen.findByText(scoutName)).toBeInTheDocument();
    },
  );

  it.each([
    [
      "a click",
      async (user: ReturnType<typeof userEvent.setup>, button: HTMLElement) => {
        await user.click(button);
      },
    ],
    [
      "an Enter press",
      async (user: ReturnType<typeof userEvent.setup>, button: HTMLElement) => {
        button.focus();
        await user.keyboard("{Enter}");
      },
    ],
  ])(
    "expands with %s without opening the surrounding row",
    async (_case, activate) => {
      const user = userEvent.setup();
      const openRow = vi.fn();
      const reviewers = Array.from({ length: 6 }, (_, index) =>
        ungroupedReviewer(index),
      );

      render(
        // biome-ignore lint/a11y/useSemanticElements: This mirrors the report row that hosts the popover.
        <div
          role="button"
          tabIndex={0}
          onClick={openRow}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === " ") {
              event.preventDefault();
              openRow();
            }
          }}
        >
          <SuggestedReviewersList reviewers={reviewers} disabled={false} />
        </div>,
      );

      expect(screen.queryByText("Dev 5")).not.toBeInTheDocument();

      await activate(
        user,
        screen.getByRole("button", { name: "Show all (6)" }),
      );

      expect(screen.getByText("Dev 5")).toBeInTheDocument();
      expect(openRow).not.toHaveBeenCalled();
    },
  );
});
