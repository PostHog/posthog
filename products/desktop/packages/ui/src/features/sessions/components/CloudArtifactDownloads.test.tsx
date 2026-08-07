import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CloudArtifactDownloads } from "./CloudArtifactDownloads";

const getCloudAttachmentPreviewUrl = vi.fn();
const setCloudRunArtifactsDismissed = vi.fn();
const openArtifactTab = vi.fn();
const setQueryData = vi.fn();
let fetchedArtifacts: unknown[] = [];

vi.mock("@posthog/core/sessions/sessionService", () => ({
  SESSION_SERVICE: Symbol("SESSION_SERVICE"),
}));

vi.mock("@posthog/di/react", () => ({
  useService: () => ({
    getCloudAttachmentPreviewUrl,
    setCloudRunArtifactsDismissed,
  }),
}));

vi.mock("@posthog/ui/features/sessions/sessionStore", () => ({
  useSessionSelector: () => undefined,
}));

vi.mock("@posthog/ui/features/auth/store", () => ({
  getAuthIdentity: () => "auth-1",
  useAuthStateValue: () => "auth-1",
}));

vi.mock("@tanstack/react-query", () => ({
  useQuery: () => ({ data: fetchedArtifacts }),
  useQueryClient: () => ({ setQueryData }),
  useMutation: ({
    mutationFn,
    onSuccess,
  }: {
    mutationFn: (variables: unknown) => Promise<unknown>;
    onSuccess: (result: unknown) => void;
  }) => ({
    isPending: false,
    mutate: (variables: unknown) => void mutationFn(variables).then(onSuccess),
  }),
}));

vi.mock("@posthog/ui/features/panels/panelLayoutStore", () => ({
  usePanelLayoutStore: () => openArtifactTab,
}));

const task = {
  id: "task-1",
  latest_run: {
    id: "run-1",
    status: "completed",
  },
} as never;

function renderDownloads() {
  return render(
    <Theme>
      <CloudArtifactDownloads taskId="task-1" task={task} />
    </Theme>,
  );
}

describe("CloudArtifactDownloads", () => {
  beforeEach(() => {
    fetchedArtifacts = [
      {
        id: "output-1",
        name: "report.pdf",
        type: "output",
        size: 12_000,
        storage_path: "tasks/run-1/report.pdf",
        uploaded_at: "2026-07-27T08:00:00+00:00",
      },
      {
        id: "internal-1",
        name: "handoff.pack",
        type: "artifact",
        storage_path: "tasks/run-1/handoff.pack",
      },
    ];
    getCloudAttachmentPreviewUrl.mockReset();
    setCloudRunArtifactsDismissed.mockReset();
    openArtifactTab.mockReset();
    setQueryData.mockReset();
    vi.restoreAllMocks();
  });

  it("shows output artifacts and opens their download URL", async () => {
    getCloudAttachmentPreviewUrl.mockResolvedValue(
      "https://files.example/report.pdf",
    );
    const fetchArtifact = vi
      .spyOn(window, "fetch")
      .mockResolvedValue(new Response("file contents"));
    const createObjectURL = vi
      .spyOn(URL, "createObjectURL")
      .mockReturnValue("blob:artifact");
    const revokeObjectURL = vi
      .spyOn(URL, "revokeObjectURL")
      .mockImplementation(() => undefined);
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(() => undefined);

    renderDownloads();

    expect(screen.getByText("report.pdf")).toBeInTheDocument();
    expect(screen.getByText("12 KB")).toBeInTheDocument();
    expect(screen.queryByText("handoff.pack")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Download"));

    await waitFor(() => expect(click).toHaveBeenCalledOnce());
    expect(fetchArtifact).toHaveBeenCalledWith(
      "https://files.example/report.pdf",
    );
    expect(createObjectURL).toHaveBeenCalledOnce();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:artifact");
    expect(getCloudAttachmentPreviewUrl).toHaveBeenCalledWith(
      "task-1",
      "run-1",
      "output-1",
    );
  });

  it("opens an artifact preview in a new tab", () => {
    renderDownloads();

    fireEvent.click(screen.getByText("report.pdf"));

    expect(openArtifactTab).toHaveBeenCalledWith("task-1", {
      runId: "run-1",
      artifactId: "output-1",
      name: "report.pdf",
    });
  });

  // A re-upload replaces the file rather than adding a second row for it.
  it("opens the newest upload of a repeated name", () => {
    fetchedArtifacts = [
      {
        id: "output-1",
        name: "report.pdf",
        type: "output",
        uploaded_at: "2026-07-27T08:00:00+00:00",
      },
      {
        id: "output-2",
        name: "report.pdf",
        type: "output",
        uploaded_at: "2026-07-27T09:00:00+00:00",
      },
    ];

    renderDownloads();

    expect(screen.getAllByText("report.pdf")).toHaveLength(1);

    fireEvent.click(screen.getByText("report.pdf"));

    expect(openArtifactTab).toHaveBeenCalledWith("task-1", {
      runId: "run-1",
      artifactId: "output-2",
      name: "report.pdf",
    });
  });

  // Dismissing the row a user sees has to take the versions behind it too,
  // otherwise the file reappears as its own older upload.
  it("dismisses every version of a file", async () => {
    fetchedArtifacts = [
      {
        id: "output-1",
        name: "report.pdf",
        type: "output",
        uploaded_at: "2026-07-27T08:00:00+00:00",
      },
      {
        id: "output-2",
        name: "report.pdf",
        type: "output",
        uploaded_at: "2026-07-27T09:00:00+00:00",
      },
    ];
    const dismissedManifest = fetchedArtifacts.map((artifact) => ({
      ...(artifact as object),
      dismissed_at: "2026-07-27T10:00:00+00:00",
    }));
    setCloudRunArtifactsDismissed.mockResolvedValue(dismissedManifest);

    renderDownloads();

    fireEvent.click(screen.getByLabelText("Dismiss report.pdf"));

    await waitFor(() =>
      expect(setCloudRunArtifactsDismissed).toHaveBeenCalledWith(
        "task-1",
        "run-1",
        ["output-2", "output-1"],
        true,
      ),
    );
    expect(setQueryData).toHaveBeenCalledWith(
      expect.anything(),
      dismissedManifest,
    );
  });

  it("hides a dismissed file until the toggle brings it back", () => {
    fetchedArtifacts = [
      {
        id: "output-1",
        name: "report.pdf",
        type: "output",
        uploaded_at: "2026-07-27T08:00:00+00:00",
        dismissed_at: "2026-07-27T10:00:00+00:00",
      },
    ];

    renderDownloads();

    expect(screen.queryByText("report.pdf")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Show 1 dismissed"));

    expect(screen.getByText("report.pdf")).toBeInTheDocument();
    expect(screen.getByText("Restore")).toBeInTheDocument();
  });

  // Collapse state lives in a module-scoped store that nothing here resets, so
  // the case that leaves the box collapsed has to run last.
  it("starts expanded and collapses when the header is clicked", () => {
    renderDownloads();

    const trigger = screen.getByRole("button", { name: "Files (1)" });
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("report.pdf")).toBeVisible();

    fireEvent.click(trigger);

    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("report.pdf")).not.toBeInTheDocument();

    fireEvent.click(trigger);

    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("report.pdf")).toBeVisible();
  });

  it("remembers collapse state per task", () => {
    const { unmount } = renderDownloads();

    fireEvent.click(screen.getByRole("button", { name: "Files (1)" }));
    expect(screen.queryByText("report.pdf")).not.toBeInTheDocument();
    unmount();

    renderDownloads();

    expect(screen.getByRole("button", { name: "Files (1)" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(screen.queryByText("report.pdf")).not.toBeInTheDocument();
  });
});
