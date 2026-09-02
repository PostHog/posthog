import type { Task } from "@posthog/shared/domain-types";
import { render } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

const { useDiffStatsToggle } = vi.hoisted(() => ({
  useDiffStatsToggle: vi.fn(() => ({
    filesChanged: 1,
    linesAdded: 2,
    linesRemoved: 3,
    isOpen: false,
    toggle: vi.fn(),
  })),
}));

vi.mock("@posthog/ui/features/code-review/hooks/useDiffStatsToggle", () => ({
  useDiffStatsToggle,
}));
vi.mock("@posthog/ui/primitives/Tooltip", () => ({
  Tooltip: ({ children }: { children: ReactNode }) => children,
}));

import { DiffStatsChip } from "./DiffStatsChip";

describe("DiffStatsChip", () => {
  it("uses the shared responsive diff-view toggle", () => {
    const task = { id: "task-1" } as Task;

    render(<DiffStatsChip task={task} />);

    expect(useDiffStatsToggle).toHaveBeenCalledWith(task);
  });
});
