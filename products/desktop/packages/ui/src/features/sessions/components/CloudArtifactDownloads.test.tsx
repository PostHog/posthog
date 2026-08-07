import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CloudArtifactDownloads } from "./CloudArtifactDownloads";

const getCloudAttachmentPreviewUrl = vi.fn();
const setCloudRunArtifactsDismissed = vi.fn();
const openArtifactTab = vi.fn();
const refetch = vi.fn();
let fetchedArtifacts: unknown[] | undefined = [];
let session: {
  cloudArtifacts?: unknown[];
  cloudStatus?: string;
  events?: unknown[];
} = {};

const UPLOAD_TOOL = "mcp__posthog-code-tools__upload_artifact";

function uploadEvent(update: Record<string, unknown>) {
  return {
    type: "acp_message",
    ts: 0,
    message: { jsonrpc: "2.0", method: "session/update", params: { update } },
  };
}

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
  useSessionSelector: (_taskId: string, select: (s: unknown) => unknown) =>
    select(session),
}));

vi.mock("@posthog/ui/features/auth/store", () => ({
  getAuthIdentity: () => "auth-1",
  useAuthStateValue: () => "auth-1",
}));

vi.mock("@tanstack/react-query", () => ({
  useQuery: () => ({ data: fetchedArtifacts, refetch }),
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
    session = {};
    refetch.mockReset();
    getCloudAttachmentPreviewUrl.mockReset();
    setCloudRunArtifactsDismissed.mockReset();
    openArtifactTab.mockReset();
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

  it("disables every download while a shared request is in progress", async () => {
    if (!fetchedArtifacts) throw new Error("artifact fixture must be loaded");
    const artifacts = fetchedArtifacts;
    artifacts.push({
      id: "output-2",
      name: "summary.txt",
      type: "output",
      size: 100,
      storage_path: "tasks/run-1/summary.txt",
    });
    let finishPreviewRequest: (url: null) => void = () => undefined;
    getCloudAttachmentPreviewUrl.mockReturnValue(
      new Promise<null>((resolve) => {
        finishPreviewRequest = resolve;
      }),
    );

    try {
      render(
        <Theme>
          <CloudArtifactDownloads taskId="task-1" task={task} />
        </Theme>,
      );

      const downloadButtons = screen.getAllByRole("button", {
        name: "Download",
      });
      fireEvent.click(downloadButtons[0]);

      await waitFor(() =>
        expect(downloadButtons[1]).toHaveAttribute("aria-disabled", "true"),
      );
      finishPreviewRequest(null);
      await waitFor(() =>
        expect(downloadButtons[1]).toHaveAttribute("aria-disabled", "false"),
      );
    } finally {
      artifacts.pop();
    }
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
    expect(
      screen.getByRole("button", { name: "Files (1)" }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByText("report.pdf"));

    expect(openArtifactTab).toHaveBeenCalledWith("task-1", {
      runId: "run-1",
      artifactId: "output-2",
      name: "report.pdf",
    });
  });

  // A manifest entry carries an id only once the upload is finalized, and a
  // version the picker cannot switch to is worse than no picker at all.
  it("switches to a version that has no id", () => {
    fetchedArtifacts = [
      {
        name: "report.pdf",
        type: "output",
        size: 1_000,
        storage_path: "tasks/run-1/report-v1.pdf",
        uploaded_at: "2026-07-27T08:00:00+00:00",
      },
      {
        name: "report.pdf",
        type: "output",
        size: 2_000,
        storage_path: "tasks/run-1/report-v2.pdf",
        uploaded_at: "2026-07-27T09:00:00+00:00",
      },
    ];

    renderDownloads();

    expect(screen.getByText("2 KB")).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("Choose a version of report.pdf"));
    fireEvent.click(screen.getByText(/^Version 1/));

    expect(screen.getByText("1 KB")).toBeInTheDocument();
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
    await waitFor(() =>
      expect(screen.getByText("Show 1 dismissed")).toBeInTheDocument(),
    );
    expect(screen.queryByText("report.pdf")).not.toBeInTheDocument();
  });

  // A dismissal must not park a snapshot anywhere that outranks the live session store, which is
  // what the box renders from before the first fetch resolves.
  it("still shows files uploaded after a mid-run dismissal", async () => {
    fetchedArtifacts = undefined;
    session = {
      cloudStatus: "in_progress",
      cloudArtifacts: [
        {
          id: "output-1",
          name: "report.pdf",
          type: "output",
          uploaded_at: "2026-07-27T08:00:00+00:00",
        },
      ],
    };
    setCloudRunArtifactsDismissed.mockResolvedValue([
      {
        id: "output-1",
        name: "report.pdf",
        type: "output",
        uploaded_at: "2026-07-27T08:00:00+00:00",
        dismissed_at: "2026-07-27T09:00:00+00:00",
      },
    ]);

    const { rerender } = renderDownloads();

    fireEvent.click(screen.getByLabelText("Dismiss report.pdf"));
    await waitFor(() =>
      expect(screen.queryByText("report.pdf")).not.toBeInTheDocument(),
    );

    session.cloudArtifacts = [
      ...(session.cloudArtifacts as unknown[]),
      {
        id: "output-2",
        name: "notes.md",
        type: "output",
        uploaded_at: "2026-07-27T10:00:00+00:00",
      },
    ];
    rerender(
      <Theme>
        <CloudArtifactDownloads taskId="task-1" task={task} />
      </Theme>,
    );

    expect(screen.getByText("notes.md")).toBeInTheDocument();
    expect(screen.queryByText("report.pdf")).not.toBeInTheDocument();
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
    expect(
      screen.getByRole("button", { name: "Files (0)" }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByText("Show 1 dismissed"));

    expect(screen.getByText("report.pdf")).toBeInTheDocument();
    expect(screen.getByText("Restore")).toBeInTheDocument();
  });

  // Nothing pushes the run's manifest to this client, so without the tool call as a trigger a
  // freshly delivered file waits for the backstop poll.
  it("rereads the manifest as soon as an upload finishes", () => {
    session = { cloudStatus: "in_progress", events: [] };

    const { rerender } = renderDownloads();
    refetch.mockClear();

    session.events = [
      uploadEvent({
        sessionUpdate: "tool_call",
        toolCallId: "call-1",
        _meta: { posthog: { toolName: UPLOAD_TOOL } },
      }),
      uploadEvent({
        sessionUpdate: "tool_call_update",
        toolCallId: "call-1",
        status: "completed",
      }),
    ];
    rerender(
      <Theme>
        <CloudArtifactDownloads taskId="task-1" task={task} />
      </Theme>,
    );

    expect(refetch).toHaveBeenCalled();
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
