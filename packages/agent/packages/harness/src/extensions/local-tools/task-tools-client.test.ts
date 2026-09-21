import { beforeEach, describe, expect, it, vi } from "vitest";
import { TaskToolsApiClient } from "./task-tools-client";

const mockFetch = vi.fn();

vi.stubGlobal("fetch", mockFetch);

describe("TaskToolsApiClient", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns only the artifacts created by the current upload request", async () => {
    const client = new TaskToolsApiClient({
      apiUrl: "https://app.posthog.com",
      getApiKey: vi.fn().mockResolvedValue("token"),
      projectId: 1,
    });

    mockFetch.mockResolvedValueOnce({
      ok: true,
      json: vi.fn().mockResolvedValue({
        artifacts: [
          { storage_path: "gs://bucket/existing.tar.gz", name: "existing" },
          { storage_path: "gs://bucket/new-1.pack", name: "new-1" },
          { storage_path: "gs://bucket/new-2.index", name: "new-2" },
        ],
      }),
    });

    const artifacts = await client.uploadTaskArtifacts("task-1", "run-1", [
      { name: "new-1", type: "artifact", content: "AAA" },
      { name: "new-2", type: "artifact", content: "BBB" },
    ]);

    expect(artifacts).toEqual([
      { storage_path: "gs://bucket/new-1.pack", name: "new-1" },
      { storage_path: "gs://bucket/new-2.index", name: "new-2" },
    ]);
  });
});
