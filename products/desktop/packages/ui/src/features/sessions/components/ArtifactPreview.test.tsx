import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ArtifactPreview } from "./ArtifactPreview";
import {
  artifactHtmlDocument,
  artifactPreviewBlob,
} from "./artifactPreviewDocument";

const previewBlob = new Blob(["<h1>Artifact content</h1>"], {
  type: "text/html",
});
const auth = vi.hoisted(() => ({ identity: "auth-1" as string | null }));
const useQuery = vi.hoisted(() => vi.fn());

vi.mock("@posthog/core/sessions/sessionService", () => ({
  SESSION_SERVICE: Symbol("SESSION_SERVICE"),
}));

vi.mock("@posthog/di/react", () => ({
  useService: () => ({}),
}));

vi.mock("@posthog/ui/features/auth/store", () => ({
  getAuthIdentity: vi.fn(),
  useAuthStateValue: () => auth.identity,
}));

vi.mock("@posthog/ui/features/auth/useCurrentUser", () => ({
  AUTH_SCOPED_QUERY_META: { authScoped: true },
}));

vi.mock("@tanstack/react-query", () => ({
  useQuery,
}));

vi.mock("../../code-editor/components/CodeMirrorEditor", () => ({
  CodeMirrorEditor: ({ content }: { content: string }) => (
    <div data-testid="source-view">{content}</div>
  ),
}));

describe("ArtifactPreview", () => {
  beforeEach(() => {
    auth.identity = "auth-1";
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

  it("shows artifact content in a fully sandboxed iframe", () => {
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

    // react-zoom-pan-pinch never clears its ~180ms wheel-stop alignment timer
    // on unmount; fired after jsdom teardown its requestAnimationFrame call
    // crashes the run, so wait it out here.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 250));
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

  it("blocks network subresources in HTML artifacts", () => {
    const document = artifactHtmlDocument(
      '<!doctype html><img src="https://internal.example/secret">',
    );

    expect(document.indexOf("Content-Security-Policy")).toBeLessThan(
      document.indexOf("<img"),
    );
    expect(document).toContain("connect-src &#39;none&#39;");
    expect(document).toContain("frame-src &#39;none&#39;");
  });
});
