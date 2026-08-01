import type { TaskRunArtifact } from "@posthog/shared";
import { createElement } from "react";
import { act, create } from "react-test-renderer";
import { describe, expect, it, vi } from "vitest";
import { TaskArtifacts } from "./TaskArtifacts";

const mockUseTaskArtifacts = vi.fn();

vi.mock("../hooks/useTaskArtifacts", () => ({
  useTaskArtifacts: (...args: unknown[]) => mockUseTaskArtifacts(...args),
}));

vi.mock("./ArtifactPreview", () => ({
  ArtifactPreview: (props: Record<string, unknown>) =>
    createElement("ArtifactPreview", props),
}));

vi.mock("../api", () => ({ presignTaskRunArtifact: vi.fn() }));

vi.mock("@/lib/openExternalUrl", () => ({ openExternalUrl: vi.fn() }));

vi.mock("phosphor-react-native", () => ({
  ArrowSquareOut: (props: Record<string, unknown>) =>
    createElement("ArrowSquareOut", props),
  File: (props: Record<string, unknown>) => createElement("File", props),
}));

vi.mock("@/lib/theme", () => ({
  useThemeColors: () => ({ gray: { 9: "#777", 11: "#555" } }),
}));

function render(artifacts: TaskRunArtifact[] | undefined) {
  mockUseTaskArtifacts.mockReturnValue({ data: artifacts });
  let renderer: ReturnType<typeof create> | null = null;
  act(() => {
    renderer = create(
      createElement(TaskArtifacts, {
        taskId: "t1",
        runId: "r1",
        enabled: true,
      }),
    );
  });
  if (!renderer) throw new Error("Renderer not created");
  return JSON.stringify((renderer as ReturnType<typeof create>).toJSON());
}

describe("TaskArtifacts", () => {
  it("renders nothing when there are no artifacts", () => {
    expect(render([])).toBe("null");
    expect(render(undefined)).toBe("null");
  });

  it("lists artifact names and sizes", () => {
    const output = render([
      { id: "a1", name: "report.md", type: "output", size: 2_400 },
      { id: "a2", name: "chart.png", type: "output", size: 512 },
    ]);
    expect(output).toContain("Files");
    expect(output).toContain("report.md");
    expect(output).toContain("chart.png");
    expect(output).toContain("2 KB");
    expect(output).toContain("512 B");
  });
});
