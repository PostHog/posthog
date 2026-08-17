import { beforeEach, describe, expect, it } from "vitest";
import {
  buildPlanReviewFeedback,
  splitPlanSections,
  usePlanReviewStore,
} from "./planReview";

describe("plan review", () => {
  beforeEach(() => {
    usePlanReviewStore.getState().clear("test-plan");
  });

  it("creates stable sections for headings and numbered steps", () => {
    expect(
      splitPlanSections(
        "# Plan\n\n## Update the API\nChange the endpoint.\n\n## Update the UI\nChange the form.",
      ),
    ).toEqual([
      {
        id: "plan",
        title: "Plan",
        content: "# Plan",
      },
      {
        id: "update-the-api",
        title: "Update the API",
        content: "## Update the API\nChange the endpoint.",
      },
      {
        id: "update-the-ui",
        title: "Update the UI",
        content: "## Update the UI\nChange the form.",
      },
    ]);
  });

  it("marks a comment stale when its section changes", () => {
    const section = splitPlanSections(
      "## Update the API\nChange the endpoint.",
    )[0];
    usePlanReviewStore.getState().addComment("test-plan", {
      sectionId: section.id,
      sectionTitle: section.title,
      sectionContent: section.content,
      text: "Use the generated client.",
    });

    usePlanReviewStore
      .getState()
      .reconcile("test-plan", [
        { ...section, content: "## Update the API\nUse a different endpoint." },
      ]);

    expect(usePlanReviewStore.getState().comments["test-plan"]?.[0].stale).toBe(
      true,
    );
  });

  it("formats multiple comments with section context and extra feedback", () => {
    const feedback = buildPlanReviewFeedback(
      [
        {
          id: "comment-1",
          sectionId: "api",
          sectionTitle: "Update the API",
          sectionContent: "## Update the API\nChange the endpoint.",
          text: "Keep the existing endpoint.",
          createdAt: 1,
          stale: false,
        },
      ],
      "Explain the migration impact.",
    );

    expect(feedback).toContain('Section "Update the API"');
    expect(feedback).toContain("Keep the existing endpoint.");
    expect(feedback).toContain("Explain the migration impact.");
  });
});
