import { Theme } from "@radix-ui/themes";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CloudArtifactDownloads } from "./CloudArtifactDownloads";

const getCloudAttachmentPreviewUrl = vi.fn();
const fetchedArtifacts = [
  {
    id: "output-1",
    name: "report.pdf",
    type: "output",
    size: 12_000,
    storage_path: "tasks/run-1/report.pdf",
  },
  {
    id: "internal-1",
    name: "handoff.pack",
    type: "artifact",
    storage_path: "tasks/run-1/handoff.pack",
  },
];

vi.mock("@posthog/core/sessions/sessionService", () => ({
  SESSION_SERVICE: Symbol("SESSION_SERVICE"),
}));

vi.mock("@posthog/di/react", () => ({
  useService: () => ({ getCloudAttachmentPreviewUrl }),
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
}));

const task = {
  id: "task-1",
  latest_run: {
    id: "run-1",
    status: "completed",
  },
} as never;

describe("CloudArtifactDownloads", () => {
  beforeEach(() => {
    getCloudAttachmentPreviewUrl.mockReset();
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

    render(
      <Theme>
        <CloudArtifactDownloads taskId="task-1" task={task} />
      </Theme>,
    );

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
});
