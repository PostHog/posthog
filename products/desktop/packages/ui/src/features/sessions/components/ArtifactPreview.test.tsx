import type { ResourceComment } from "@posthog/api-client/posthog-client";
import { useCommentNavigationStore } from "@posthog/ui/features/sessions/commentNavigationStore";
import { TooltipProvider } from "@radix-ui/react-tooltip";
import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import type { ReactNode } from "react";
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  type MockInstance,
  vi,
} from "vitest";
import { ArtifactPreview } from "./ArtifactPreview";
import {
  artifactHtmlDocument,
  artifactPreviewBlob,
  scriptedArtifactHtmlDocument,
} from "./artifactPreviewDocument";

const previewBlob = new Blob(["<h1>Artifact content</h1>"], {
  type: "text/html",
});
const auth = vi.hoisted(() => ({ identity: "auth-1" as string | null }));
const artifactComments = vi.hoisted(() => ({
  data: [] as ResourceComment[],
  isError: false,
}));
const createComment = vi.hoisted(() => vi.fn());
const useQuery = vi.hoisted(() => vi.fn());
const commentsFlag = vi.hoisted(() => ({ enabled: true }));
const orgMembersOptions = vi.hoisted(() => vi.fn());

vi.mock("@posthog/ui/features/sessions/useCommentsEnabled", () => ({
  useCommentsEnabled: () => commentsFlag.enabled,
}));

vi.mock("@posthog/core/sessions/sessionService", () => ({
  SESSION_SERVICE: Symbol("SESSION_SERVICE"),
}));

vi.mock("@posthog/di/react", () => ({
  useService: () => ({}),
  useServiceOptional: () => null,
}));

vi.mock("@posthog/ui/features/auth/store", () => ({
  getAuthIdentity: vi.fn(),
  useAuthStateValue: () => auth.identity,
}));

vi.mock("@posthog/ui/features/auth/useCurrentUser", () => ({
  AUTH_SCOPED_QUERY_META: { authScoped: true },
}));

vi.mock("@posthog/ui/features/canvas/hooks/useOrgMembers", () => ({
  useOrgMembers: (options: { enabled?: boolean }) => {
    orgMembersOptions(options);
    return { members: [] };
  },
}));

vi.mock("@posthog/ui/features/canvas/components/MentionComposer", () => ({
  MentionComposer: ({
    value,
    onValueChange,
    placeholder,
    children,
  }: {
    value: string;
    onValueChange: (value: string) => void;
    placeholder?: string;
    children: ReactNode;
  }) => (
    <div>
      <textarea
        aria-label="Comment text"
        placeholder={placeholder}
        value={value}
        onChange={(event) => onValueChange(event.target.value)}
      />
      {children}
    </div>
  ),
}));

vi.mock("@tanstack/react-query", () => ({
  useQuery,
}));

vi.mock("./useComments", () => ({
  useCommentsQuery: () => ({
    data: artifactComments.data,
    isLoading: false,
    isError: artifactComments.isError,
  }),
  useCreateComment: () => ({ mutateAsync: createComment, isPending: false }),
}));

vi.mock("../../code-editor/components/CodeMirrorEditor", () => ({
  CodeMirrorEditor: ({ content }: { content: string }) => (
    <div data-testid="source-view">{content}</div>
  ),
}));

function textComment(): ResourceComment {
  return {
    id: "comment-1",
    created_by: null,
    content: "Tighten this summary",
    created_at: "2026-01-01T00:00:00Z",
    item_id: "artifact-1",
    item_context: {
      anchor: {
        kind: "text",
        quote: "Report",
        prefix: "# ",
        suffix: "",
        start: 2,
        end: 8,
      },
    },
    scope: "task_artifact",
    source_comment: null,
    completed_at: null,
  };
}

describe("ArtifactPreview", () => {
  beforeEach(() => {
    commentsFlag.enabled = true;
    auth.identity = "auth-1";
    useCommentNavigationStore.setState({
      focusByTask: {},
      resolutionsByTarget: {},
    });
    artifactComments.data = [];
    artifactComments.isError = false;
    createComment.mockReset();
    createComment.mockResolvedValue({ id: "created-comment" });
    useQuery.mockReset();
    useQuery.mockReturnValue({
      data: previewBlob,
      isLoading: false,
      isError: false,
    });
    vi.spyOn(URL, "createObjectURL").mockReturnValue("blob:preview");
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(() => undefined);
  });

  it("scopes cached previews to the authenticated identity", () => {
    render(
      <ArtifactPreview
        taskId="task-1"
        runId="run-1"
        artifactId="artifact-1"
        name="report.html"
      />,
    );

    expect(useQuery).toHaveBeenCalledWith(
      expect.objectContaining({
        queryKey: [
          "artifactPreview",
          "auth-1",
          "task-1",
          "run-1",
          "artifact-1",
        ],
        enabled: true,
        meta: { authScoped: true },
      }),
    );
  });

  it("keeps the artifact visible when comments fail to load", () => {
    artifactComments.isError = true;
    useQuery.mockReturnValue({
      data: "# Report",
      isLoading: false,
      isError: false,
    });

    render(
      <ArtifactPreview
        taskId="task-1"
        runId="run-1"
        artifactId="artifact-1"
        name="report.md"
      />,
    );

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Couldn't load comments. Refresh to try again.",
    );
    expect(screen.getByText("Report")).toBeInTheDocument();
  });

  it("disables preview fetching without an authenticated identity", () => {
    auth.identity = null;
    render(
      <ArtifactPreview
        taskId="task-1"
        runId="run-1"
        artifactId="artifact-1"
        name="report.html"
      />,
    );

    expect(useQuery).toHaveBeenCalledWith(
      expect.objectContaining({ enabled: false, meta: { authScoped: true } }),
    );
  });

  it("renders authored HTML in an opaque-origin annotation iframe", () => {
    useQuery.mockReturnValue({
      data: {
        kind: "html",
        html: "<style>h1{color:red}</style><h1>Artifact content</h1>",
      },
      isLoading: false,
      isError: false,
    });
    render(
      <ArtifactPreview
        taskId="task-1"
        runId="run-1"
        artifactId="artifact-1"
        name="report.html"
      />,
    );

    const frame = screen.getByTitle("Preview of report.html");
    expect(frame).toHaveAttribute("src", "blob:preview");
    expect(frame).toHaveAttribute("sandbox", "allow-scripts");
    expect(frame).toHaveAttribute("referrerpolicy", "no-referrer");
  });

  it("keeps comment controls and the HTML bridge out while comments are disabled", async () => {
    commentsFlag.enabled = false;
    useQuery.mockReturnValue({
      data: { kind: "html", html: "<h1>Artifact content</h1>" },
      isLoading: false,
      isError: false,
    });

    render(
      <ArtifactPreview
        taskId="task-1"
        runId="run-1"
        artifactId="artifact-1"
        name="report.html"
      />,
    );

    expect(orgMembersOptions).toHaveBeenLastCalledWith({ enabled: false });

    expect(screen.queryByText("Comment…")).toBeNull();
    const documentBlob = vi.mocked(URL.createObjectURL).mock.calls[0]?.[0];
    expect(documentBlob).toBeInstanceOf(Blob);
    await expect(
      new Response(documentBlob as Blob).text(),
    ).resolves.not.toContain("__POSTHOG_ARTIFACT_COMMENT_BRIDGE__");
  });

  // Same zoom-and-annotate surface as a raster image: an <img> renders SVG in a
  // secure static mode, so it doesn't need the sandboxed-iframe fallback.
  it("gives SVG the image controls rather than an iframe", () => {
    useQuery.mockReturnValue({
      data: new Blob(["<svg/>"], { type: "image/svg+xml" }),
      isLoading: false,
      isError: false,
    });

    render(
      <ArtifactPreview
        taskId="task-1"
        runId="run-1"
        artifactId="artifact-1"
        name="diagram.svg"
      />,
    );

    expect(screen.getByRole("img", { name: "diagram.svg" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Zoom in" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Pin comment…" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Comment…" })).toBeTruthy();
    expect(screen.queryByTitle("Preview of diagram.svg")).toBeNull();
  });

  it("keeps opaque formats in a fully sandboxed iframe", () => {
    render(
      <ArtifactPreview
        taskId="task-1"
        runId="run-1"
        artifactId="artifact-1"
        name="report.pdf"
      />,
    );

    const frame = screen.getByTitle("Preview of report.pdf");
    expect(frame).toHaveAttribute("src", "blob:preview");
    expect(frame).toHaveAttribute("sandbox", "");
  });

  it.each([
    ["image.png", "image/png"],
    ["image.jpg", "image/jpeg"],
    ["image.gif", "image/gif"],
    ["image.webp", "image/webp"],
    ["image.bmp", "image/bmp"],
    ["image.ico", "image/x-icon"],
    ["image.tiff", "image/tiff"],
    ["image.avif", "image/avif"],
  ])("normalizes %s served as octet-stream", async (name, mimeType) => {
    const blob = await artifactPreviewBlob(
      new Blob(["image"], { type: "application/octet-stream" }),
      name,
    );

    expect(blob.type).toBe(mimeType);
  });

  // A download often arrives untyped, and the preview picks its surface off the
  // blob's type, so the extension has to supply it.
  it("types an SVG blob from its filename", async () => {
    const blob = await artifactPreviewBlob(
      new Blob(["<svg/>"], { type: "" }),
      "diagram.svg",
    );

    expect(blob.type).toBe("image/svg+xml");
  });

  it("shows working image controls instead of an iframe", () => {
    useQuery.mockReturnValue({
      data: new Blob(["image"], { type: "image/png" }),
      isLoading: false,
      isError: false,
    });

    render(
      <ArtifactPreview
        taskId="task-1"
        runId="run-1"
        artifactId="artifact-1"
        name="image.png"
      />,
    );

    expect(screen.getByRole("img", { name: "image.png" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Zoom in" })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Zoom out" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Fit to view" }),
    ).toBeInTheDocument();
    expect(screen.queryByTitle("Preview of image.png")).not.toBeInTheDocument();

    const zoomOut = screen.getByRole("button", { name: "Zoom out" });
    fireEvent.click(zoomOut);
    fireEvent.click(zoomOut);
    fireEvent.click(zoomOut);
    fireEvent.click(zoomOut);
    expect(screen.getByText("10%")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Fit to view" }));
    expect(screen.getByText("100%")).toBeInTheDocument();
  });

  it("zooms with a trackpad pinch gesture", async () => {
    useQuery.mockReturnValue({
      data: new Blob(["image"], { type: "image/png" }),
      isLoading: false,
      isError: false,
    });

    render(
      <ArtifactPreview
        taskId="task-1"
        runId="run-1"
        artifactId="artifact-1"
        name="image.png"
      />,
    );

    const image = screen.getByRole("img", { name: "image.png" });
    const viewport = image.closest(".react-transform-wrapper");
    expect(viewport).not.toBeNull();
    fireEvent.wheel(viewport as Element, {
      ctrlKey: true,
      deltaY: -100,
      clientX: 100,
      clientY: 100,
    });

    await waitFor(() => {
      const percentage = Number.parseInt(
        screen.getByText(/%$/).textContent ?? "0",
        10,
      );
      expect(percentage).toBeGreaterThan(100);
    });
  });

  it("shows the preview error when an image cannot be decoded", () => {
    useQuery.mockReturnValue({
      data: new Blob(["not an image"], { type: "image/png" }),
      isLoading: false,
      isError: false,
    });

    render(
      <ArtifactPreview
        taskId="task-1"
        runId="run-1"
        artifactId="artifact-1"
        name="broken.png"
      />,
    );

    fireEvent.error(screen.getByRole("img", { name: "broken.png" }));
    expect(
      screen.getByText("This artifact can’t be previewed."),
    ).toBeInTheDocument();
  });

  it("renders Markdown artifacts with the file preview styling", () => {
    useQuery.mockReturnValue({
      data: "# Report\n\n**Ready**\n\n| Name | Value |\n| --- | --- |\n| Cost | 12 |",
      isLoading: false,
      isError: false,
    });

    const { container } = render(
      <ArtifactPreview
        taskId="task-1"
        runId="run-1"
        artifactId="artifact-1"
        name="report.md"
      />,
    );

    expect(screen.getByRole("heading", { name: "Report" })).toBeInTheDocument();
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(
      container.querySelector(".plan-markdown.mx-auto"),
    ).toBeInTheDocument();
    expect(screen.getByText("report.md")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "View source" }));

    expect(screen.getByTestId("source-view")).toHaveTextContent("# Report");
    expect(
      screen.getByRole("button", { name: "View preview" }),
    ).toBeInTheDocument();
  });

  it("creates an anchored comment from rendered Markdown text", async () => {
    useQuery.mockReturnValue({
      data: "# Report",
      isLoading: false,
      isError: false,
    });
    render(
      <TooltipProvider>
        <ArtifactPreview
          taskId="task-1"
          runId="run-1"
          artifactId="artifact-1"
          name="report.md"
        />
      </TooltipProvider>,
    );

    const heading = screen.getByRole("heading", { name: "Report" });
    const range = document.createRange();
    range.selectNodeContents(heading);
    range.getBoundingClientRect = () =>
      ({ top: 0, left: 20, right: 120, bottom: 20 }) as DOMRect;
    window.getSelection()?.removeAllRanges();
    window.getSelection()?.addRange(range);
    fireEvent.mouseUp(heading);

    fireEvent.click(await screen.findByRole("button", { name: "Add comment" }));
    fireEvent.change(
      screen.getByPlaceholderText("Add a comment about this selection..."),
      { target: { value: "Tighten this title" } },
    );
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Comment" }));
    });

    expect(createComment).toHaveBeenCalledWith({
      content: "Tighten this title",
      context: {
        anchor: expect.objectContaining({ kind: "text", quote: "Report" }),
      },
      mentions: [],
    });
  });

  it("dismisses the Markdown comment action when clicking away", async () => {
    useQuery.mockReturnValue({
      data: "# Report",
      isLoading: false,
      isError: false,
    });
    render(
      <TooltipProvider>
        <ArtifactPreview
          taskId="task-1"
          runId="run-1"
          artifactId="artifact-1"
          name="report.md"
        />
      </TooltipProvider>,
    );
    const heading = screen.getByRole("heading", { name: "Report" });
    const range = document.createRange();
    range.selectNodeContents(heading);
    range.getBoundingClientRect = () =>
      ({ top: 0, left: 20, right: 120, bottom: 20 }) as DOMRect;
    window.getSelection()?.removeAllRanges();
    window.getSelection()?.addRange(range);
    fireEvent.mouseUp(heading);
    expect(
      await screen.findByRole("button", { name: "Add comment" }),
    ).toBeTruthy();

    fireEvent.pointerDown(document.body);

    expect(screen.queryByRole("button", { name: "Add comment" })).toBeNull();
  });

  it("keeps the DOM selection when it collapses outside the Markdown root", async () => {
    useQuery.mockReturnValue({
      data: "# Report",
      isLoading: false,
      isError: false,
    });
    render(
      <TooltipProvider>
        <ArtifactPreview
          taskId="task-1"
          runId="run-1"
          artifactId="artifact-1"
          name="report.md"
        />
      </TooltipProvider>,
    );
    const heading = screen.getByRole("heading", { name: "Report" });
    const range = document.createRange();
    range.selectNodeContents(heading);
    range.getBoundingClientRect = () =>
      ({ top: 0, left: 20, right: 120, bottom: 20 }) as DOMRect;
    window.getSelection()?.removeAllRanges();
    window.getSelection()?.addRange(range);
    fireEvent.mouseUp(heading);
    expect(
      await screen.findByRole("button", { name: "Add comment" }),
    ).toBeTruthy();

    // A collapsed selection elsewhere (e.g. a caret placed in an input) must
    // close the overlay without wiping the document selection — clearing it
    // here steals the caret and cancels in-progress drag selections.
    window.getSelection()?.collapse(document.body, 0);

    await waitFor(() =>
      expect(screen.queryByRole("button", { name: "Add comment" })).toBeNull(),
    );
    expect(window.getSelection()?.rangeCount).toBe(1);
  });

  it("does not render resolved comment highlights", () => {
    const root: ResourceComment = {
      id: "comment-1",
      created_by: null,
      content: "Review this",
      created_at: "2026-01-01T00:00:00Z",
      item_id: "artifact-1",
      item_context: {
        anchor: {
          kind: "text",
          quote: "Report",
          prefix: "# ",
          suffix: "",
          start: 2,
          end: 8,
        },
      },
      scope: "task_artifact",
      source_comment: null,
      completed_at: null,
    };
    artifactComments.data = [
      root,
      {
        ...root,
        id: "state-1",
        content: "Resolved this thread",
        created_at: "2026-01-01T00:01:00Z",
        source_comment: root.id,
        item_context: {
          anchor: { kind: "document" },
          threadState: "resolved",
        },
      },
    ];
    useQuery.mockReturnValue({
      data: "# Report",
      isLoading: false,
      isError: false,
    });

    render(
      <ArtifactPreview
        taskId="task-1"
        runId="run-1"
        artifactId="artifact-1"
        name="report.md"
      />,
    );

    expect(
      screen.queryByLabelText("Open comment from Unknown user"),
    ).toBeNull();
  });

  it("highlights a Markdown comment that arrives after the preview renders", async () => {
    Range.prototype.getClientRects = () =>
      [{ left: 0, top: 0, width: 40, height: 12 }] as unknown as DOMRectList;
    try {
      useQuery.mockReturnValue({
        data: "# Report",
        isLoading: false,
        isError: false,
      });
      const view = () => (
        <ArtifactPreview
          taskId="task-1"
          runId="run-1"
          artifactId="artifact-1"
          name="report.md"
        />
      );
      const { rerender } = render(view());
      expect(
        screen.queryByLabelText("Open comment from Unknown user"),
      ).toBeNull();

      artifactComments.data = [textComment()];
      rerender(view());

      expect(
        await screen.findByLabelText("Open comment from Unknown user"),
      ).toHaveStyle({
        backgroundColor: "rgba(250, 204, 21, 0.32)",
      });
    } finally {
      Reflect.deleteProperty(Range.prototype, "getClientRects");
    }
  });

  // Both directions of the cross-pane bridge, since the list and the artifact
  // sit in sibling React trees and can only talk through the store. jsdom has
  // no layout, so the highlight geometry and the scroll are stubbed.
  describe("with the comment list in the sidebar", () => {
    const rect = { left: 0, top: 0, width: 40, height: 12 } as DOMRect;
    let scrollIntoView: MockInstance;

    beforeEach(() => {
      scrollIntoView = vi.spyOn(Element.prototype, "scrollIntoView");
      // jsdom has no range geometry at all, so unlike the scroll (stubbed in
      // the shared setup) the highlight rectangles have to be supplied.
      Range.prototype.getClientRects = () => [rect] as unknown as DOMRectList;
      artifactComments.data = [textComment()];
      useQuery.mockReturnValue({
        data: "# Report",
        isLoading: false,
        isError: false,
      });
    });

    afterEach(() => {
      Reflect.deleteProperty(Range.prototype, "getClientRects");
      scrollIntoView.mockRestore();
    });

    it("hands a thread picked on the artifact over to the list", async () => {
      render(
        <ArtifactPreview
          taskId="task-1"
          runId="run-1"
          artifactId="artifact-1"
          name="report.md"
        />,
      );

      fireEvent.click(
        await screen.findByLabelText("Open comment from Unknown user"),
      );

      expect(
        useCommentNavigationStore.getState().focusByTask["task-1"],
      ).toEqual({
        target: { scope: "task_artifact", itemId: "artifact-1" },
        threadId: "comment-1",
        nonce: expect.any(Number),
        openCommentsTab: true,
      });
    });

    it("scrolls to the anchor the list asks for", async () => {
      useCommentNavigationStore
        .getState()
        .requestCommentFocus(
          "task-1",
          { scope: "task_artifact", itemId: "artifact-1" },
          "comment-1",
        );

      render(
        <ArtifactPreview
          taskId="task-1"
          runId="run-1"
          artifactId="artifact-1"
          name="report.md"
        />,
      );

      await waitFor(() => expect(scrollIntoView).toHaveBeenCalled());
      // And the thread reads as the active one on the surface.
      const highlight = await screen.findByLabelText(
        "Open comment from Unknown user",
      );
      expect(highlight).toHaveStyle({
        backgroundColor: "rgba(250, 204, 21, 0.48)",
      });
    });

    // A thread from another artifact must not drag this one around.
    it("ignores a focus request aimed at a different artifact", async () => {
      useCommentNavigationStore
        .getState()
        .requestCommentFocus(
          "task-1",
          { scope: "task_artifact", itemId: "artifact-2" },
          "comment-1",
        );

      render(
        <ArtifactPreview
          taskId="task-1"
          runId="run-1"
          artifactId="artifact-1"
          name="report.md"
        />,
      );

      await screen.findByLabelText("Open comment from Unknown user");
      expect(scrollIntoView).not.toHaveBeenCalled();
    });
  });

  // The pane is the artifact: its threads are listed in the task's Comments
  // tab, so nothing here may render or toggle a second list of them.
  it("keeps the pane free of a thread list", () => {
    // Document-anchored, so this asserts the missing list rather than tripping
    // over jsdom's lack of range geometry for highlights.
    artifactComments.data = [
      { ...textComment(), item_context: { anchor: { kind: "document" } } },
    ];
    useQuery.mockReturnValue({
      data: "# Report",
      isLoading: false,
      isError: false,
    });

    render(
      <ArtifactPreview
        taskId="task-1"
        runId="run-1"
        artifactId="artifact-1"
        name="report.md"
      />,
    );

    expect(screen.queryByRole("button", { name: /comments/i })).toBeNull();
    expect(screen.queryByText("Tighten this summary")).toBeNull();
  });

  it("preserves authored styles and injects the inline-comment bridge", () => {
    const document = artifactHtmlDocument(
      '<!doctype html><html><head><style>.card{color:red}</style></head><body><div class="card" style="font-size:20px">Report</div></body></html>',
      "test-channel",
    );

    expect(document).toContain("<style>.card{color:red}</style>");
    expect(document).toContain('style="font-size:20px"');
    expect(document).toContain("__POSTHOG_ARTIFACT_COMMENT_BRIDGE__");
    expect(document).toContain("posthog-artifact-comment-active");
    expect(document).not.toContain("ph-artifact-comment-outline");
    expect(document).toContain("<span>Comment</span>");
    expect(document).toContain('var CHANNEL="test-channel"');
    expect(document).toContain('d.type==="locate"');
    expect(document).toContain('send("open-external",{href:link.href})');
    expect(document).toContain('target.closest("a[href]")');
    expect(document).toContain("scrollIntoView");
    expect(document).toContain("new MutationObserver");
    expect(document).toContain("state.renderTimer");
    expect(document).toMatch(/script-src &#39;nonce-[^&]+&#39;/);
    expect(document).not.toContain(
      "script-src &#39;self&#39; &#39;unsafe-inline&#39;",
    );
  });

  it("allows embedded scripts without allowing network access", () => {
    const document = scriptedArtifactHtmlDocument(
      '<script>document.body.dataset.rendered="yes"</script>',
      "test-channel",
    );

    expect(document).toContain('document.body.dataset.rendered="yes"');
    expect(document).toContain(
      "script-src &#39;self&#39; &#39;unsafe-inline&#39;",
    );
    expect(document).toContain("connect-src &#39;none&#39;");
  });

  it("does not parse HTML without a possible refresh directive", () => {
    const parse = vi.spyOn(DOMParser.prototype, "parseFromString");

    artifactHtmlDocument(
      "<!doctype html><html><body><p>Report</p></body></html>",
      "test-channel",
    );

    expect(parse).not.toHaveBeenCalled();
    parse.mockRestore();
  });

  it("keeps sensitive capabilities blocked in HTML artifacts", () => {
    const document = artifactHtmlDocument(
      '<!doctype html><img src="https://images.example/report.png">',
    );

    expect(document.indexOf("Content-Security-Policy")).toBeLessThan(
      document.indexOf("<img"),
    );
    expect(document).toContain("connect-src &#39;none&#39;");
    expect(document).toContain("frame-src &#39;none&#39;");
    expect(document).toContain("form-action &#39;none&#39;");
    expect(document).toContain("img-src &#39;self&#39; data:");
    expect(document).toContain("script-src &#39;none&#39;");
  });

  it.each([
    '<meta http-equiv="refresh" content="0;url=https://example.com">',
    '<META content="5; https://example.com" HTTP-EQUIV=" Refresh ">',
  ])("removes automatic redirects from HTML artifacts", (refreshElement) => {
    const document = artifactHtmlDocument(
      `<!doctype html><html><head>${refreshElement}<title>Report</title></head><body><a href="https://example.com">Open report</a></body></html>`,
      "test-channel",
    );

    expect(document.toLowerCase()).not.toContain('http-equiv="refresh"');
    expect(document).toContain('<a href="https://example.com">Open report</a>');
    expect(document).toContain("__POSTHOG_ARTIFACT_COMMENT_BRIDGE__");
  });
});
