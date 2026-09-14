import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { OnboardingLanding } from "./OnboardingLanding";

const taskSpaceHrefs = {
  general: "/spaces/general-id/new",
  personal: "/spaces/personal-id/new",
};

describe("OnboardingLanding", () => {
  it.each([
    [null, "onboarding-start-tasks-general", "tasks", taskSpaceHrefs.general],
    [null, "onboarding-start-tasks-personal", "tasks", taskSpaceHrefs.personal],
    ["@posthog in Slack", "onboarding-start-slack", "slack", "/settings/slack"],
    ["Self-driving", "onboarding-start-self-driving", "self-driving", "/inbox"],
    [
      null,
      "onboarding-start-autoresearch",
      "autoresearch",
      `${taskSpaceHrefs.general}?mode=autoresearch`,
    ],
  ])(
    "opens %s via %s as a new app tab",
    async (tab, dataAttr, destination, href) => {
      const onOpenDestination = vi.fn();
      const { container } = render(
        <OnboardingLanding
          selfDrivingAvailable
          autoresearchAvailable
          taskSpaceHrefs={taskSpaceHrefs}
          onOpenDestination={onOpenDestination}
        />,
      );

      if (tab) {
        await userEvent.click(screen.getByRole("tab", { name: tab }));
      }
      const button = container.querySelector(`[data-attr="${dataAttr}"]`);
      if (!button) throw new Error(`Expected ${dataAttr}`);
      await userEvent.click(button);

      expect(onOpenDestination).toHaveBeenCalledWith(destination, href);
    },
  );

  it("keeps the loops action disabled while loops are coming soon", async () => {
    const onOpenDestination = vi.fn();
    const { container } = render(
      <OnboardingLanding
        selfDrivingAvailable
        autoresearchAvailable
        taskSpaceHrefs={taskSpaceHrefs}
        onOpenDestination={onOpenDestination}
      />,
    );

    await userEvent.click(
      screen.getByRole("tab", { name: "Loops Coming soon" }),
    );
    const button = container.querySelector(
      '[data-attr="onboarding-start-loops"]',
    );

    expect(button).toHaveAttribute("aria-disabled", "true");
    if (!button) throw new Error("Expected the loops action");
    await userEvent.click(button);
    expect(onOpenDestination).not.toHaveBeenCalled();
  });

  it("hides self-driving and autoresearch when they are unavailable", () => {
    const { container } = render(
      <OnboardingLanding
        selfDrivingAvailable={false}
        autoresearchAvailable={false}
        taskSpaceHrefs={taskSpaceHrefs}
        onOpenDestination={vi.fn()}
      />,
    );

    expect(
      container.querySelector('[data-attr="onboarding-start-tasks-general"]'),
    ).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Self-driving" })).toBeNull();
    expect(
      container.querySelector('[data-attr="onboarding-start-autoresearch"]'),
    ).toBeNull();
  });
});
