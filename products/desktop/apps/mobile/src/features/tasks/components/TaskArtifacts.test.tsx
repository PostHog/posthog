import type { TaskRunArtifact } from "@posthog/shared";
import { createElement } from "react";
import { act, create } from "react-test-renderer";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TaskArtifacts } from "./TaskArtifacts";

const mockUseTaskArtifacts = vi.fn();
const mockUseUserQuery = vi.fn();
const dismissTaskRunArtifacts = vi.fn(async () => [] as TaskRunArtifact[]);

vi.mock("../hooks/useTaskArtifacts", () => ({
  useTaskArtifacts: (...args: unknown[]) => mockUseTaskArtifacts(...args),
}));

vi.mock("@/features/auth", () => ({
  useUserQuery: () => mockUseUserQuery(),
}));

vi.mock("../api", () => ({
  presignTaskRunArtifact: vi.fn(),
  dismissTaskRunArtifacts: (...args: unknown[]) =>
    dismissTaskRunArtifacts(...(args as [])),
}));

vi.mock("@tanstack/react-query", () => ({
  useMutation: (opts: {
    mutationFn: (vars: unknown) => Promise<unknown>;
    onSuccess?: (data: unknown) => void;
    onError?: (error: unknown) => void;
  }) => ({
    isPending: false,
    mutate: (vars: unknown) => {
      Promise.resolve(opts.mutationFn(vars)).then(
        opts.onSuccess ?? (() => undefined),
        opts.onError ?? (() => undefined),
      );
    },
  }),
}));

vi.mock("@/components/SheetContainer", () => ({
  SheetContainer: ({
    open,
    children,
  }: {
    open: boolean;
    children: React.ReactNode;
  }) => (open ? createElement("SheetContainer", null, children) : null),
}));

vi.mock("./ArtifactPreview", () => ({
  ArtifactPreview: (props: Record<string, unknown>) =>
    createElement("ArtifactPreview", props),
}));

vi.mock("@/lib/openExternalUrl", () => ({ openExternalUrl: vi.fn() }));

vi.mock("phosphor-react-native", () => ({
  CaretDown: (props: Record<string, unknown>) =>
    createElement("CaretDown", props),
  Check: (props: Record<string, unknown>) => createElement("Check", props),
  DownloadSimple: (props: Record<string, unknown>) =>
    createElement("DownloadSimple", props),
  File: (props: Record<string, unknown>) => createElement("File", props),
  Package: (props: Record<string, unknown>) => createElement("Package", props),
  X: (props: Record<string, unknown>) => createElement("X", props),
}));

vi.mock("@/lib/theme", () => ({
  useThemeColors: () => ({
    gray: { 4: "#eee", 10: "#888", 11: "#555", 12: "#111" },
    accent: { 9: "#09f", 11: "#06c" },
  }),
}));

function element() {
  return createElement(TaskArtifacts, {
    taskId: "t1",
    runId: "r1",
    enabled: true,
  });
}

function mount(artifacts: TaskRunArtifact[] | undefined) {
  mockUseTaskArtifacts.mockReturnValue({ data: artifacts, refetch: vi.fn() });
  let renderer: ReturnType<typeof create> | null = null;
  act(() => {
    renderer = create(element());
  });
  if (!renderer) throw new Error("Renderer not created");
  return renderer as ReturnType<typeof create>;
}

function json(renderer: ReturnType<typeof create>) {
  return JSON.stringify(renderer.toJSON());
}

function pressLabel(renderer: ReturnType<typeof create>, label: string) {
  const node = renderer.root.findByProps({ accessibilityLabel: label });
  act(() => {
    node.props.onPress();
  });
}

function openSheet(renderer: ReturnType<typeof create>) {
  const trigger = renderer.root.find((node) =>
    Boolean(
      (node.props.accessibilityLabel as string | undefined)?.startsWith(
        "Files (",
      ),
    ),
  );
  act(() => {
    trigger.props.onPress();
  });
}

function hasLabel(renderer: ReturnType<typeof create>, label: string): boolean {
  return (
    renderer.root.findAll((node) => node.props.accessibilityLabel === label)
      .length > 0
  );
}

describe("TaskArtifacts", () => {
  beforeEach(() => {
    dismissTaskRunArtifacts.mockClear();
    mockUseUserQuery.mockReturnValue({ data: { id: 7 } });
  });

  it("renders nothing when there are no artifacts", () => {
    expect(json(mount([]))).toBe("null");
    expect(json(mount(undefined))).toBe("null");
  });

  it("shows a count on the trigger and lists files once opened", () => {
    const renderer = mount([
      { id: "a1", name: "report.md", type: "output", size: 2_400 },
      { id: "a2", name: "chart.png", type: "output", size: 512 },
    ]);
    expect(hasLabel(renderer, "Files (2)")).toBe(true);
    expect(json(renderer)).not.toContain("report.md");

    openSheet(renderer);
    const shown = json(renderer);
    expect(shown).toContain("report.md");
    expect(shown).toContain("chart.png");
  });

  it("shows the version picker only when a file has more than one version", () => {
    const renderer = mount([
      {
        id: "a1",
        name: "report.md",
        type: "output",
        uploaded_at: "2024-01-01T00:00:00Z",
      },
      {
        id: "a2",
        name: "report.md",
        type: "output",
        uploaded_at: "2024-02-01T00:00:00Z",
      },
      { id: "b1", name: "chart.png", type: "output" },
    ]);
    openSheet(renderer);

    expect(hasLabel(renderer, "Choose a version of report.md")).toBe(true);
    expect(hasLabel(renderer, "Choose a version of chart.png")).toBe(false);
  });

  it("labels the uploader as the current user, a teammate, or the agent", () => {
    const renderer = mount([
      {
        id: "a1",
        name: "mine.md",
        type: "output",
        uploaded_by: "user",
        uploaded_by_user_id: 7,
      },
      {
        id: "a2",
        name: "theirs.md",
        type: "output",
        uploaded_by: "user",
        uploaded_by_user_id: 99,
      },
      { id: "a3", name: "agent.md", type: "output", uploaded_by: "agent" },
    ]);
    openSheet(renderer);

    const shown = json(renderer);
    expect(shown).toContain("You");
    expect(shown).toContain("Teammate");
    expect(shown).toContain("Agent");
  });

  it("dismisses a file through the api", () => {
    const renderer = mount([
      { id: "a1", name: "report.md", type: "output", size: 2_400 },
    ]);
    openSheet(renderer);

    pressLabel(renderer, "Dismiss report.md");

    expect(dismissTaskRunArtifacts).toHaveBeenCalledWith(
      "t1",
      "r1",
      ["a1"],
      true,
    );
  });

  it("restores a dismissed file through the api", () => {
    const renderer = mount([
      {
        id: "a1",
        name: "report.md",
        type: "output",
        dismissed_at: "2024-03-01T00:00:00Z",
      },
    ]);
    expect(hasLabel(renderer, "Files (0)")).toBe(true);

    openSheet(renderer);
    pressLabel(renderer, "Show 1 dismissed");
    pressLabel(renderer, "Restore report.md");

    expect(dismissTaskRunArtifacts).toHaveBeenCalledWith(
      "t1",
      "r1",
      ["a1"],
      false,
    );
  });
});
