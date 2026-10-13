import type { Task } from "@posthog/shared/domain-types";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@posthog/ui/features/canvas/hooks/useChannelsLayout", () => ({
  useChannelsLayout: () => false,
}));

vi.mock("@posthog/ui/features/sidebar/useTaskPrStatus", () => ({
  useTaskPrStatus: () => ({ prState: "open", hasDiff: false }),
}));

import { TaskCommandIcon } from "./TaskCommandIcon";

const task: Task = {
  id: "task-1",
  task_number: 1,
  slug: "keep-ci-green",
  title: "Keep CI green",
  description: "Monitor the pull request checks.",
  created_at: "2026-09-07T12:00:00Z",
  updated_at: "2026-09-07T12:00:00Z",
  origin_product: "user_created",
  latest_run: {
    id: "run-1",
    task: "task-1",
    team: 2,
    branch: null,
    status: "in_progress",
    environment: "cloud",
    log_url: "",
    error_message: null,
    output: null,
    state: { mode: "background" },
    created_at: "2026-09-07T12:00:00Z",
    updated_at: "2026-09-07T12:00:00Z",
    completed_at: null,
  },
};

describe("TaskCommandIcon", () => {
  it("shows active background work before an existing pull request", () => {
    render(<TaskCommandIcon task={task} />);

    expect(screen.getByRole("img", { name: "Working" })).toBeInTheDocument();
  });
});
