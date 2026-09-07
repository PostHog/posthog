import type { TaskRunArtifact } from "@posthog/shared";
import { MarkdownRenderer } from "@posthog/ui/features/editor/components/MarkdownRenderer";
import { ChatMarkdown } from "@posthog/ui/features/sessions/components/chat-thread/ChatMarkdown";
import { SessionTaskIdProvider } from "@posthog/ui/features/sessions/useSessionTaskId";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const TASK_ID = "3f1c2b6a-1111-4222-8333-444455556666";
const RUN_ID = "9a8b7c6d-5555-4666-8777-888899990000";
const ARTIFACT_ID = "1a2b3c4d-2222-4333-8444-555566667777";
const STORAGE_PATH = `posthog-tasks/artifacts/team_2/task_${TASK_ID}/run_${RUN_ID}/1a2b3c4d_report.md`;
const LEGACY_LINK = `https://bucket.s3.amazonaws.com/${STORAGE_PATH}?X-Amz-Signature=abc`;
const STABLE_LINK = `https://app.posthog.com/api/projects/2/tasks/${TASK_ID}/runs/${RUN_ID}/artifacts/${ARTIFACT_ID}/download/`;

const manifest = vi.hoisted(() => ({
  data: undefined as TaskRunArtifact[] | undefined,
  isLoading: false,
}));
const openArtifactTab = vi.hoisted(() => vi.fn());
const download = vi.hoisted(() => vi.fn());

vi.mock("@posthog/ui/features/sessions/useRunArtifacts", () => ({
  useRunArtifacts: () => manifest,
}));

vi.mock("@posthog/ui/features/sessions/useArtifactDownload", () => ({
  useArtifactDownload: () => ({ download, downloadingId: null }),
}));

vi.mock("@posthog/ui/features/panels/panelLayoutStore", () => ({
  usePanelLayoutStore: (selector: (state: unknown) => unknown) =>
    selector({ openArtifactTab }),
}));

// Agent replies render through two markdown surfaces — the app-wide renderer and
// the chat thread's own. A link has to become a chip in both.
const SURFACES = [
  ["MarkdownRenderer", MarkdownRenderer],
  ["ChatMarkdown", ChatMarkdown],
] as const;

let renderSurface: (typeof SURFACES)[number][1] = MarkdownRenderer;

function renderMessage(content: string, taskId: string | undefined = TASK_ID) {
  const Surface = renderSurface;
  return render(
    <SessionTaskIdProvider taskId={taskId}>
      <Surface content={content} />
    </SessionTaskIdProvider>,
  );
}

describe.each(SURFACES)("artifact links in messages (%s)", (_name, Surface) => {
  beforeEach(() => {
    renderSurface = Surface;
    vi.clearAllMocks();
    manifest.isLoading = false;
    manifest.data = [
      {
        id: ARTIFACT_ID,
        name: "report.md",
        type: "output",
        size: 2048,
        storage_path: STORAGE_PATH,
      },
    ];
  });

  it.each([
    ["legacy storage", LEGACY_LINK],
    ["stable download", STABLE_LINK],
  ])(
    "opens a %s link in a tab instead of leaving the app",
    async (_kind, link) => {
      renderMessage(`Here it is: [report.md](${link})`);

      await userEvent.click(
        await screen.findByRole("button", { name: "Open report.md" }),
      );

      expect(openArtifactTab).toHaveBeenCalledWith(TASK_ID, {
        runId: RUN_ID,
        artifactId: ARTIFACT_ID,
        name: "report.md",
      });
      expect(screen.queryByRole("link")).toBeNull();
    },
  );

  it("downloads from the divided half without opening a tab", async () => {
    renderMessage(`Here it is: [report.md](${LEGACY_LINK})`);

    await userEvent.click(
      await screen.findByRole("button", { name: "Download report.md" }),
    );

    expect(download).toHaveBeenCalledWith({
      taskId: TASK_ID,
      runId: RUN_ID,
      artifactId: ARTIFACT_ID,
      name: "report.md",
    });
    expect(openArtifactTab).not.toHaveBeenCalled();
  });

  it("holds an inert chip while the manifest is still loading", async () => {
    manifest.data = undefined;
    manifest.isLoading = true;
    renderMessage(`Here it is: [report.md](${LEGACY_LINK})`);

    expect(screen.queryByRole("link")).toBeNull();
    // quill keeps a disabled button focusable, so `aria-disabled` is where it
    // says so rather than the native attribute.
    expect(
      await screen.findByRole("button", { name: "Open report.md" }),
    ).toHaveAttribute("aria-disabled", "true");
  });

  it.each([
    ["legacy storage", LEGACY_LINK],
    ["stable download", STABLE_LINK],
  ])("labels a bare %s url with the manifest filename", async (_kind, link) => {
    renderMessage(`Here it is: ${link}`);

    const chip = await screen.findByRole("button", { name: "Open report.md" });
    expect(chip).toHaveTextContent("report.md");
    expect(chip).not.toHaveTextContent("https://");
  });

  it("keeps a stable link when the artifact is no longer in the manifest", async () => {
    manifest.data = [];
    renderMessage(`Here it is: [report.md](${STABLE_LINK})`);

    await waitFor(() => {
      expect(screen.getByRole("link")).toHaveAttribute("href", STABLE_LINK);
    });
    expect(screen.queryByRole("button", { name: "Open report.md" })).toBeNull();
  });

  it.each([
    [
      "the link belongs to another task",
      () => {},
      "other-task-id" as string | undefined,
    ],
    [
      "the artifact is no longer in the manifest",
      () => {
        manifest.data = [];
      },
      TASK_ID as string | undefined,
    ],
    [
      "the manifest never loads because nobody is signed in",
      () => {
        manifest.data = undefined;
        manifest.isLoading = false;
      },
      TASK_ID as string | undefined,
    ],
  ])("keeps the plain link when %s", async (_label, mutate, taskId) => {
    mutate();
    renderMessage(`Here it is: [report.md](${LEGACY_LINK})`, taskId);

    await waitFor(() => {
      expect(screen.getByRole("link")).toHaveAttribute("href", LEGACY_LINK);
    });
    expect(screen.queryByRole("button", { name: "Open report.md" })).toBeNull();
  });
});
