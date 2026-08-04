import type { ToolCall } from "@posthog/ui/features/sessions/types";
import { Theme } from "@radix-ui/themes";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TasksSpawnToolView } from "./TasksSpawnToolView";

describe("TasksSpawnToolView", () => {
  it("renders child details instead of raw JSON", () => {
    const toolCall: ToolCall = {
      toolCallId: "spawn-1",
      title: "tasks-spawn",
      kind: "other",
      status: "in_progress",
      rawInput: {
        title: "Implement focused fix",
        description: "Change the serializer and add tests.",
        repository: "PostHog/posthog",
        delegation_profile: "low",
        wake_on: ["pr_merged"],
      },
    };

    render(
      <Theme>
        <TasksSpawnToolView toolCall={toolCall} />
      </Theme>,
    );

    expect(screen.getByText("Spawn child task")).toBeInTheDocument();
    expect(screen.getByText("Implement focused fix")).toBeInTheDocument();
    expect(
      screen.getByText("Change the serializer and add tests."),
    ).toBeInTheDocument();
    expect(screen.getByText("low profile")).toBeInTheDocument();
    expect(screen.getByText("pr_merged")).toBeInTheDocument();
  });
});
