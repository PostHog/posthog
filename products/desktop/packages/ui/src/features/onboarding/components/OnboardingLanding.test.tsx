import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { OnboardingLanding } from "./OnboardingLanding";

describe("OnboardingLanding", () => {
  it.each([
    ["Open spaces", "spaces", "/spaces"],
    ["Open self-driving", "self-driving", "/inbox"],
    ["Open canvases", "canvases", "/canvases"],
    ["Open agents", "agents", "/agents"],
    ["Open tasks", "tasks", "/new"],
  ])("requests a new app tab from %s", async (label, destination, href) => {
    const onOpenDestination = vi.fn();
    render(
      <OnboardingLanding
        selfDrivingAvailable
        onOpenDestination={onOpenDestination}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Current" }));
    await userEvent.click(screen.getByText(label));

    expect(onOpenDestination).toHaveBeenCalledWith(destination, href);
  });

  it("explains personal and public spaces without a separate multiplayer card", async () => {
    render(
      <OnboardingLanding selfDrivingAvailable onOpenDestination={vi.fn()} />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Current" }));
    expect(
      screen.getByText(
        "Spaces keep related work, context, and people together. Use them for your own work or to work with others.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Personal space" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Public space" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Feed" })).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Context" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Context stores the space's shared CONTEXT.md with conventions, key files, and other background. Agents read it when relevant to their task.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText("Multiplayer")).toBeNull();
  });

  it("hides self-driving when the destination is unavailable", async () => {
    render(
      <OnboardingLanding
        selfDrivingAvailable={false}
        onOpenDestination={vi.fn()}
      />,
    );

    expect(screen.queryByText("Self-driving")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Flow" }));

    expect(screen.queryByText("Self-driving")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Compact" }));

    expect(screen.queryByText("Self-driving")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Rail" }));

    expect(screen.queryByText("Self-driving")).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Cycle" }));

    expect(screen.queryByText("Self-driving")).toBeNull();
  });

  it("shows the guided design by default and switches to the current design", async () => {
    render(
      <OnboardingLanding selfDrivingAvailable onOpenDestination={vi.fn()} />,
    );

    const design = document.querySelector('[data-attr="onboarding-design"]');
    expect(design).toHaveAttribute("data-design", "guided");
    expect(
      screen.getByText(
        "Learn how work moves from an idea to a completed result.",
      ),
    ).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Current" }));

    expect(design).toHaveAttribute("data-design", "current");
    expect(
      screen.getByText(
        "Choose a concept to learn more. Each link opens in a new tab.",
      ),
    ).toBeInTheDocument();
  });

  it("opens a new task from the guided start card", async () => {
    const onOpenDestination = vi.fn();
    render(
      <OnboardingLanding
        selfDrivingAvailable
        onOpenDestination={onOpenDestination}
      />,
    );

    await userEvent.click(
      screen.getByRole("link", { name: "Create your first task in a new tab" }),
    );

    expect(onOpenDestination).toHaveBeenCalledWith("tasks", "/new");
  });

  it("expands the compact space definitions in the guided design", async () => {
    render(
      <OnboardingLanding selfDrivingAvailable onOpenDestination={vi.fn()} />,
    );

    await userEvent.click(
      screen.getByRole("button", { name: "Inside a space" }),
    );

    expect(screen.getByText("Private work")).toBeVisible();
    expect(screen.getByText("Shared team work")).toBeVisible();
    expect(screen.getByText("Sessions and replies")).toBeVisible();
    expect(screen.getByText("Shared agent background")).toBeVisible();
  });

  it("shows the work paths in the flow design", async () => {
    render(
      <OnboardingLanding selfDrivingAvailable onOpenDestination={vi.fn()} />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Flow" }));

    expect(
      screen.getByRole("heading", { name: "How work moves through Desktop" }),
    ).toBeVisible();
    expect(screen.getAllByText("Signup errors increased")).toHaveLength(2);
    expect(screen.getByText("Start the next attempt")).toBeVisible();
    expect(screen.getByText("Coming soon")).toBeVisible();
    expect(screen.getByText("Send to agent")).toBeVisible();
    expect(screen.getByRole("heading", { name: "Canvas" })).toBeVisible();
    expect(
      screen.queryByText("Feedback continues the work"),
    ).not.toBeInTheDocument();
  });

  it("shows a compact map with UI previews outside the labels", async () => {
    const onOpenDestination = vi.fn();
    render(
      <OnboardingLanding
        selfDrivingAvailable
        onOpenDestination={onOpenDestination}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Compact" }));

    expect(
      screen.getByRole("heading", { name: "From idea to result" }),
    ).toBeVisible();
    expect(screen.getByRole("heading", { name: "User input" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Self-driving" })).toBeVisible();
    expect(await screen.findByRole("heading", { name: "Loops" })).toBeVisible();
    expect(screen.getByText("Coming soon")).toBeVisible();
    expect(screen.getByRole("heading", { name: "Autoresearch" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Agent work" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Code change" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Canvas" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Report" })).toBeVisible();

    await userEvent.click(
      screen.getByRole("link", { name: "Open User input in a new tab" }),
    );
    expect(onOpenDestination).toHaveBeenCalledWith("tasks", "/new");
  });

  it("shows a left-aligned rail with vertical input choices", async () => {
    const onOpenDestination = vi.fn();
    render(
      <OnboardingLanding
        selfDrivingAvailable
        onOpenDestination={onOpenDestination}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Rail" }));

    expect(
      screen.getByRole("heading", {
        name: "How work moves through Desktop",
      }),
    ).toBeVisible();
    expect(screen.getAllByText("or")).toHaveLength(3);
    expect(screen.getByText("Coming soon")).toBeVisible();
    expect(screen.getByText("Possible results")).toBeVisible();
    expect(screen.getByRole("heading", { name: "Agent work" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Code change" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Canvas" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Report" })).toBeVisible();

    await userEvent.click(
      screen.getByRole("link", { name: "Open Self-driving in a new tab" }),
    );
    expect(onOpenDestination).toHaveBeenCalledWith("self-driving", "/inbox");
  });

  it("shows a cycling input with static results and no slider controls", async () => {
    const onOpenDestination = vi.fn();
    render(
      <OnboardingLanding
        selfDrivingAvailable
        onOpenDestination={onOpenDestination}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Cycle" }));

    expect(screen.getByRole("heading", { name: "User input" })).toBeVisible();
    expect(
      screen.getByRole("heading", { name: "Build the task" }),
    ).toBeVisible();
    expect(screen.getByRole("heading", { name: "Code change" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Report" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Canvas" })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Loops" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Show input/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Show result/ })).toBeNull();
    expect(
      document.querySelector(".onboarding-cycle-flow__traveler"),
    ).toBeInTheDocument();

    await userEvent.click(screen.getByText("Create a task"));

    expect(onOpenDestination).toHaveBeenCalledWith("tasks", "/new");
  });

  it("cycles inputs and pauses while the input is hovered", () => {
    vi.useFakeTimers();

    try {
      render(
        <OnboardingLanding selfDrivingAvailable onOpenDestination={vi.fn()} />,
      );

      fireEvent.click(screen.getByRole("button", { name: "Cycle" }));

      const inputStage = document.querySelector(
        '[data-attr="onboarding-cycle-input-stage"]',
      );
      const agentStage = document.querySelector(
        '[data-attr="onboarding-cycle-agent-stage"]',
      );
      expect(inputStage).toBeInTheDocument();
      expect(agentStage).toBeInTheDocument();
      if (!inputStage) throw new Error("Expected the cycling input stage");
      if (!agentStage) throw new Error("Expected the cycling agent stage");

      expect(inputStage).toHaveAttribute(
        "data-active-path",
        "Task to code change",
      );
      expect(agentStage).toHaveAttribute(
        "data-active-path",
        "Task to code change",
      );
      expect(screen.queryByRole("button", { name: /Show input/ })).toBeNull();
      expect(screen.queryByRole("button", { name: /Show result/ })).toBeNull();

      fireEvent.pointerEnter(inputStage);
      act(() => vi.advanceTimersByTime(5_100));

      expect(inputStage).toHaveAttribute(
        "data-active-path",
        "Task to code change",
      );

      fireEvent.pointerLeave(inputStage);
      act(() => vi.advanceTimersByTime(5_000));

      expect(inputStage).toHaveAttribute(
        "data-active-path",
        "Signal to report",
      );
      expect(agentStage).toHaveAttribute(
        "data-active-path",
        "Task to code change",
      );

      act(() => vi.advanceTimersByTime(499));
      expect(agentStage).toHaveAttribute(
        "data-active-path",
        "Task to code change",
      );

      act(() => vi.advanceTimersByTime(1));
      expect(agentStage).toHaveAttribute(
        "data-active-path",
        "Signal to report",
      );

      act(() => vi.advanceTimersByTime(5_100));
      expect(inputStage).toHaveAttribute("data-active-path", "Loop to report");
      expect(agentStage).toHaveAttribute(
        "data-active-path",
        "Signal to report",
      );

      act(() => vi.advanceTimersByTime(700));
      expect(agentStage).toHaveAttribute("data-active-path", "Loop to report");
    } finally {
      vi.useRealTimers();
    }
  });
});
