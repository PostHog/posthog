import { describe, expect, it } from "vitest";
import { getAutomationTemplatePresentation } from "./automationTemplatePresentation";

describe("automationTemplatePresentation", () => {
  it("prefers repository context when one exists for skill-backed automations", () => {
    expect(
      getAutomationTemplatePresentation({
        repository: "posthog/posthog",
        template_id: "llm-skill:shared-daily-brief",
      }),
    ).toMatchObject({
      templateName: "shared-daily-brief",
      repositoryLabel: "posthog/posthog",
      contextLabel: "Skill store",
      secondaryLabel: "posthog/posthog",
    });
  });

  it("falls back to skill-store context when no repository is present", () => {
    expect(
      getAutomationTemplatePresentation({
        repository: "",
        template_id: "llm-skill:shared-daily-brief",
      }),
    ).toMatchObject({
      templateName: "shared-daily-brief",
      repositoryLabel: null,
      contextLabel: "Skill store",
      secondaryLabel: "Skill store",
    });
  });

  it("handles unknown template ids and blank repositories safely", () => {
    expect(
      getAutomationTemplatePresentation({
        repository: "",
        template_id: "unknown-template",
      }),
    ).toMatchObject({
      templateName: "Template automation",
      repositoryLabel: null,
      contextLabel: null,
      secondaryLabel: "No repository context",
    });
  });
});
