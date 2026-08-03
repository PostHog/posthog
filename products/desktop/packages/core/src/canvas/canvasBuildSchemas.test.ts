import { describe, expect, it, vi } from "vitest";
import {
  type CanvasBuildLifecycle,
  type CanvasBuildRecord,
  hasActiveCanvasBuild,
  latestFinishedCanvasBuild,
  publishedCanvasBuild,
} from "./canvasBuildSchemas";
import { DashboardsService } from "./dashboardsService";
import type { DesktopFsClient } from "./desktopFsClient";

function build(
  id: string,
  buildStatus: CanvasBuildRecord["buildStatus"],
): CanvasBuildRecord {
  return {
    id,
    sourceVersionId: `sv-${id}`,
    buildStatus,
    diagnostics: [],
    manifest: null,
    artifactUrl:
      buildStatus === "ready" ? "https://usercontent.example/index.html" : null,
    pinned: false,
    createdAt: "2026-07-26T00:00:00Z",
    finishedAt:
      buildStatus === "queued" || buildStatus === "building"
        ? null
        : "2026-07-26T00:01:00Z",
  };
}

function lifecycle(builds: CanvasBuildRecord[]): CanvasBuildLifecycle {
  return { publishedBuildId: null, currentSourceVersionId: null, builds };
}

describe("canvas build lifecycle", () => {
  // hasActiveCanvasBuild drives the polling interval: a wrong answer either
  // polls forever or stops while a build is still running.
  it.each([
    ["queued build keeps polling", [build("b1", "queued")], true],
    [
      "running build keeps polling",
      [build("b1", "building"), build("b0", "ready")],
      true,
    ],
    [
      "settled lifecycle stops polling",
      [build("b1", "failed"), build("b0", "ready")],
      false,
    ],
    ["no builds stops polling", [], false],
  ])("%s", (_name, builds, active) => {
    expect(hasActiveCanvasBuild(lifecycle(builds))).toBe(active);
  });

  it("surfaces the newest finished build, skipping in-flight ones", () => {
    const finished = latestFinishedCanvasBuild(
      lifecycle([
        build("b2", "queued"),
        build("b1", "failed"),
        build("b0", "ready"),
      ]),
    );
    expect(finished?.id).toBe("b1");
  });

  it("selects only the ready build named by the published pointer", () => {
    const ready = build("b0", "ready");
    const value = lifecycle([build("b1", "failed"), ready]);
    value.publishedBuildId = "b0";

    expect(publishedCanvasBuild(value)).toBe(ready);
  });

  it("maps the builds endpoint's snake_case body to the client shape", async () => {
    const fetchMock = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            published_build_id: "b0",
            current_source_version_id: "sv-1",
            builds: [
              {
                id: "b1",
                source_version_id: "sv-1",
                build_status: "failed",
                diagnostics: [
                  {
                    severity: "error",
                    code: "import_not_allowed",
                    message: "no lodash",
                  },
                ],
                artifact_url: null,
                pinned: false,
                created_at: "2026-07-26T00:00:00Z",
                finished_at: "2026-07-26T00:01:00Z",
              },
            ],
          }),
          { status: 200 },
        ),
    );
    const service = new DashboardsService(
      { fetch: fetchMock } as unknown as DesktopFsClient,
      {} as never,
    );

    const result = await service.getBuilds("canvas-1");

    expect(fetchMock).toHaveBeenCalledWith("canvas-1/canvas/builds/");
    expect(result.publishedBuildId).toBe("b0");
    expect(result.builds[0]).toMatchObject({
      id: "b1",
      sourceVersionId: "sv-1",
      buildStatus: "failed",
    });
    expect(result.builds[0].diagnostics[0].code).toBe("import_not_allowed");
  });
});
