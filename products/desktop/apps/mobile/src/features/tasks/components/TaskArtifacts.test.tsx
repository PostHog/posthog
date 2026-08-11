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
  CaretDown: (props: Record<string, unknown>) =>
    createElement("CaretDown", props),
  CaretRight: (props: Record<string, unknown>) =>
    createElement("CaretRight", props),
  File: (props: Record<string, unknown>) => createElement("File", props),
}));

vi.mock("@/lib/theme", () => ({
  useThemeColors: () => ({ gray: { 9: "#777", 11: "#555" } }),
}));

function element() {
  return createElement(TaskArtifacts, {
    taskId: "t1",
    runId: "r1",
    enabled: true,
  });
}

function mount(artifacts: TaskRunArtifact[] | undefined) {
  mockUseTaskArtifacts.mockReturnValue({ data: artifacts });
  let renderer: ReturnType<typeof create> | null = null;
  act(() => {
    renderer = create(element());
  });
  if (!renderer) throw new Error("Renderer not created");
  return renderer as ReturnType<typeof create>;
}

function update(
  renderer: ReturnType<typeof create>,
  artifacts: TaskRunArtifact[] | undefined,
) {
  mockUseTaskArtifacts.mockReturnValue({ data: artifacts });
  act(() => {
    renderer.update(element());
  });
}

function json(renderer: ReturnType<typeof create>) {
  return JSON.stringify(renderer.toJSON());
}

function render(artifacts: TaskRunArtifact[] | undefined) {
  return json(mount(artifacts));
}

function pressHeader(renderer: ReturnType<typeof create>) {
  const header = renderer.root.findByProps({ accessibilityRole: "button" });
  act(() => {
    header.props.onPress();
  });
}

describe("TaskArtifacts", () => {
  it("renders nothing when there are no artifacts", () => {
    expect(render([])).toBe("null");
    expect(render(undefined)).toBe("null");
  });

  it("lists artifact names and sizes, expanded by default", () => {
    const output = render([
      { id: "a1", name: "report.md", type: "output", size: 2_400 },
      { id: "a2", name: "chart.png", type: "output", size: 512 },
    ]);
    expect(output).toContain("Files (2)");
    expect(output).toContain("report.md");
    expect(output).toContain("chart.png");
    expect(output).toContain("2 KB");
    expect(output).toContain("512 B");
  });

  it("hides the list when the header is tapped and shows it again", () => {
    const renderer = mount([
      { id: "a1", name: "report.md", type: "output", size: 2_400 },
    ]);
    expect(json(renderer)).toContain("report.md");

    pressHeader(renderer);
    const collapsed = json(renderer);
    expect(collapsed).toContain("Files (1)");
    expect(collapsed).not.toContain("report.md");

    pressHeader(renderer);
    expect(json(renderer)).toContain("report.md");
  });

  it("stays collapsed across a re-render with the same files", () => {
    const files: TaskRunArtifact[] = [
      { id: "a1", name: "report.md", type: "output", size: 2_400 },
    ];
    const renderer = mount(files);
    pressHeader(renderer);
    expect(json(renderer)).not.toContain("report.md");

    update(renderer, [...files]);
    expect(json(renderer)).not.toContain("report.md");
  });

  it("re-expands when the file list changes", () => {
    const renderer = mount([
      { id: "a1", name: "report.md", type: "output", size: 2_400 },
    ]);
    pressHeader(renderer);
    expect(json(renderer)).not.toContain("report.md");

    update(renderer, [
      { id: "a1", name: "report.md", type: "output", size: 2_400 },
      { id: "a2", name: "chart.png", type: "output", size: 512 },
    ]);
    const shown = json(renderer);
    expect(shown).toContain("report.md");
    expect(shown).toContain("chart.png");
  });
});
