import type { SuggestedReviewer } from "@posthog/shared/types";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { SuggestedReviewersList } from "./SuggestedReviewersList";

describe("SuggestedReviewersList", () => {
  it("keeps a scout name in the source tooltip", async () => {
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

    render(<SuggestedReviewersList reviewers={[reviewer]} disabled={false} />);

    expect(screen.getByText("Added by scout")).toBeInTheDocument();
    expect(screen.queryByText(scoutName)).not.toBeInTheDocument();

    await user.hover(screen.getByText("Added by scout"));
    expect(await screen.findByText(scoutName)).toBeInTheDocument();
  });
});
