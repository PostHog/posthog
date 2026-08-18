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

  it("includes content before the first section", () => {
    expect(
      splitPlanSections(
        "Review every step before approval.\n\n## Update the API\nChange the endpoint.",
      ),
    ).toEqual([
      {
        id: "update-the-api",
        title: "Update the API",
        content:
          "Review every step before approval.\n\n## Update the API\nChange the endpoint.",
      },
    ]);
  });

  it("ignores section markers inside fenced code blocks", () => {
    expect(
      splitPlanSections(
        "## Update the docs\n\n```md\n# Example heading\n1. Example step\n```\n\n## Run tests",
      ),
    ).toEqual([
      {
        id: "update-the-docs",
        title: "Update the docs",
        content:
          "## Update the docs\n\n```md\n# Example heading\n1. Example step\n```",
      },
      {
        id: "run-tests",
        title: "Run tests",
        content: "## Run tests",
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
