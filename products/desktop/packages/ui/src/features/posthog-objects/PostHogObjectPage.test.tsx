import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PostHogObjectPage } from "./PostHogObjectPage";

const writeText = vi.fn().mockResolvedValue(undefined);

vi.mock("@posthog/ui/hooks/useAuthenticatedQuery", () => ({
  useAuthenticatedQuery: () => ({
    isPending: false,
    isError: false,
    data: {
      title: "new-checkout-flow",
      detail: "Enabled",
      facts: ["100% rollout", "Used by 1 experiment"],
    },
  }),
}));

vi.mock("@posthog/ui/features/editor/components/EvidenceRefChip", () => ({
  useEvidenceUrl: () => "https://us.posthog.com/project/2/feature_flags/42",
}));

describe("PostHogObjectPage", () => {
  it("renders live reference details and copies the exact identifier", async () => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    render(
      <Theme>
        <PostHogObjectPage
          fallbackName="Flag fallback"
          metadata={{
            reference_type: "posthog_object",
            object_kind: "flag",
            object_id: "new-checkout-flow",
            source_message_ids: ["turn-1", "turn-2"],
            occurrence_count: 2,
          }}
        />
      </Theme>,
    );

    expect(screen.getAllByText("new-checkout-flow")).toHaveLength(2);
    expect(screen.getByText("100% rollout")).toBeInTheDocument();
    expect(
      screen.getByText("Referenced 2 times in this task"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Copy reference" }));
    expect(writeText).toHaveBeenCalledWith("new-checkout-flow");
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "Reference copied" }),
      ).toBeInTheDocument(),
    );
  });
});
