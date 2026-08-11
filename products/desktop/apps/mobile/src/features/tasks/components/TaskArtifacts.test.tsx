import type { TaskRunArtifact } from "@posthog/shared";
import { createElement } from "react";
import { act, create } from "react-test-renderer";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { TaskArtifacts } from "./TaskArtifacts";

const mockUseTaskArtifacts = vi.fn();
const mockUpload = vi.fn();

interface UploadState {
  isPending?: boolean;
  isError?: boolean;
  error?: Error;
  variables?: { fileName: string };
}

let uploadState: UploadState = {};

vi.mock("../hooks/useTaskArtifacts", () => ({
  useTaskArtifacts: (...args: unknown[]) => mockUseTaskArtifacts(...args),
}));

vi.mock("../hooks/useUploadTaskRunArtifact", () => ({
  useUploadTaskRunArtifact: () => ({
    mutate: mockUpload,
    isPending: uploadState.isPending ?? false,
    isError: uploadState.isError ?? false,
    error: uploadState.error ?? null,
    variables: uploadState.variables,
  }),
}));

vi.mock("../composer/attachments/AttachmentSheet", () => ({
  AttachmentSheet: (props: Record<string, unknown>) =>
    createElement("AttachmentSheet", props),
}));

vi.mock("../composer/attachments/pickers", () => ({
  captureFromCamera: vi.fn(),
  pickDocument: vi.fn(),
  pickPhotoFromLibrary: vi.fn(),
}));

vi.mock("./ArtifactPreview", () => ({
  ArtifactPreview: (props: Record<string, unknown>) =>
    createElement("ArtifactPreview", props),
}));

vi.mock("../api", () => ({ presignTaskRunArtifact: vi.fn() }));

vi.mock("@/lib/shareUrl", () => ({ shareUrl: vi.fn() }));

vi.mock("phosphor-react-native", () => ({
  CaretDown: (props: Record<string, unknown>) =>
    createElement("CaretDown", props),
  CaretRight: (props: Record<string, unknown>) =>
    createElement("CaretRight", props),
  Export: (props: Record<string, unknown>) => createElement("Export", props),
  File: (props: Record<string, unknown>) => createElement("File", props),
  Plus: (props: Record<string, unknown>) => createElement("Plus", props),
}));

vi.mock("@/lib/theme", () => ({
  useThemeColors: () => ({ gray: { 9: "#777", 11: "#555", 12: "#111" } }),
}));

beforeEach(() => {
  uploadState = {};
  mockUpload.mockClear();
});

function mount(
  artifacts: TaskRunArtifact[] | undefined,
  { enabled = true }: { enabled?: boolean } = {},
) {
  mockUseTaskArtifacts.mockReturnValue({ data: artifacts });
  let renderer!: ReturnType<typeof create>;
  act(() => {
    renderer = create(
      createElement(TaskArtifacts, { taskId: "t1", runId: "r1", enabled }),
    );
  });
  return renderer;
}

function json(renderer: ReturnType<typeof create>) {
  return JSON.stringify(renderer.toJSON());
}

function render(artifacts: TaskRunArtifact[] | undefined) {
  return json(mount(artifacts));
}

function pressHeader(renderer: ReturnType<typeof create>) {
  const header = renderer.root.find(
    (node) =>
      typeof node.props.accessibilityLabel === "string" &&
      node.props.accessibilityLabel.startsWith("Files ("),
  );
  act(() => {
    header.props.onPress();
  });
}

describe("TaskArtifacts", () => {
  it("renders nothing while the run is not terminal", () => {
    expect(json(mount([], { enabled: false }))).toBe("null");
  });

  it("still offers 'Add file' when the run produced nothing", () => {
    const output = render([]);
    expect(output).toContain("Files (0)");
    expect(output).toContain("Add file");
    expect(output).toContain("No files yet.");
  });

  it("renders the empty state before the manifest arrives", () => {
    expect(render(undefined)).toContain("Add file");
  });

  it("uploads the file the picker returns", async () => {
    const renderer = mount([]);
    const sheet = renderer.root.findByType("AttachmentSheet" as never);
    const attachment = { id: "p1", fileName: "notes.md" };
    const { pickDocument } = await import("../composer/attachments/pickers");
    vi.mocked(pickDocument).mockResolvedValue(
      attachment as unknown as Awaited<ReturnType<typeof pickDocument>>,
    );

    await act(async () => {
      sheet.props.onPickDocument();
    });

    expect(mockUpload).toHaveBeenCalledWith(attachment);
  });

  it("shows progress while an upload is in flight", () => {
    uploadState = { isPending: true, variables: { fileName: "notes.md" } };
    const output = render([]);
    expect(output).toContain("Uploading");
    expect(output).toContain("notes.md");
  });

  it("offers a retry that resends the failed attachment", () => {
    const failed = { fileName: "notes.md" };
    uploadState = {
      isError: true,
      error: new Error("notes.md is empty."),
      variables: failed,
    };
    const renderer = mount([]);
    expect(json(renderer)).toContain("notes.md is empty.");

    act(() => {
      renderer.root
        .findByProps({ accessibilityLabel: "Retry upload" })
        .props.onPress();
    });
    expect(mockUpload).toHaveBeenCalledWith(failed);
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

  it("badges each artifact with its type", () => {
    const output = render([
      { id: "a1", name: "plan.md", type: "plan" },
      { id: "a2", name: "notes.md", type: "context" },
      { id: "a3", name: "report.md", type: "output" },
    ]);
    expect(output).toContain("Plan");
    expect(output).toContain("Context");
    expect(output).toContain("Output");
  });

  it("offers a share action per artifact", () => {
    const renderer = mount([
      { id: "a1", name: "report.md", type: "output", storage_path: "s/1" },
    ]);
    expect(
      renderer.root.findByProps({ accessibilityLabel: "Share report.md" }),
    ).toBeTruthy();
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
});
