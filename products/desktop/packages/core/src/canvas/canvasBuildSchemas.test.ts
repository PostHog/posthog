import { describe, expect, it, vi } from "vitest";
import {
  type CanvasBuildLifecycle,
  type CanvasBuildRecord,
  canvasBuildRecordSchema,
  currentHeadBuildFailure,
  hasActiveCanvasBuild,
  historicalCanvasBuild,
  latestFinishedCanvasBuild,
  placementComponentBuild,
  publishedCanvasBuild,
} from "./canvasBuildSchemas";
import { DashboardsService } from "./dashboardsService";
import type { ProjectApiClient } from "./projectApiClient";

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
  return { publishedBuildId: null, currentVersionId: null, builds };
}

describe("canvas build lifecycle", () => {
  // The builder freezes project.capabilities into the manifest verbatim, and
  // a project declares only the capabilities it uses. A partial manifest must
  // parse with deny-by-default fills — an unparseable record is silently
  // dropped, which rendered a ready build as "failed to build" on grid tiles.
  it("parses a manifest declaring only the capabilities the project uses", () => {
    const parsed = canvasBuildRecordSchema.parse({
      ...build("b1", "ready"),
      manifest: {
        entryHtml: "index.html",
        assets: [],
        dependencies: { react: "19.0.0" },
        canvasSdkVersion: "0.1.0",
        capabilities: {
          posthog: { state: ["user"] },
          network: { origins: [] },
        },
      },
    });
    expect(parsed.manifest?.capabilities.posthog).toMatchObject({
      insights: [],
      inlineQueries: false,
      captureEvents: [],
      state: ["user"],
    });
  });

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

  it("selects a retained ready artifact for a historical version", () => {
    const ready = build("historical", "ready");
    ready.sourceVersionId = "version-1";

    expect(
      historicalCanvasBuild(
        lifecycle([build("latest", "ready"), ready]),
        "version-1",
      ),
    ).toBe(ready);
  });

  it.each([
    ["an unfinished build", build("historical", "building")],
    [
      "a ready build without a retained artifact",
      { ...build("historical", "ready"), artifactUrl: null },
    ],
  ])("rejects %s for a historical version", (_name, candidate) => {
    candidate.sourceVersionId = "version-1";

    expect(
      historicalCanvasBuild(lifecycle([candidate]), "version-1"),
    ).toBeNull();
  });

  // A pinned placement's config and size were written against the version it
  // names, so rendering the live build instead would feed the widget a
  // contract nobody validated it for.
  it("renders a pinned placement from the pinned version's own build", () => {
    const pinned = build("pinned", "ready");
    pinned.sourceVersionId = "version-1";
    const value = lifecycle([build("live", "ready"), pinned]);
    value.publishedBuildId = "live";

    expect(placementComponentBuild(value, "version-1")).toBe(pinned);
  });

  // Build retention can sweep a pinned version's artifact (only an explicit
  // pin action protects a build), and falling back to the live build would
  // silently render a different widget than the placement asked for.
  it("resolves no build when the pinned version's artifact is gone", () => {
    const value = lifecycle([build("live", "ready")]);
    value.publishedBuildId = "live";

    expect(placementComponentBuild(value, "version-1")).toBeNull();
  });

  it("follows the published pointer when the placement pins nothing", () => {
    const live = build("live", "ready");
    const value = lifecycle([live, build("older", "ready")]);
    value.publishedBuildId = "live";

    expect(placementComponentBuild(value, null)).toBe(live);
  });

  it("surfaces a failed build of the current head even when an older published build is also ready", () => {
    // b_old (sv-old) is the pinned/published live build; a newer publish (b_new,
    // sv-new = current head) failed. latestFinishedCanvasBuild returns the first
    // finished build in array order, which here is the ready b_old — position,
    // not version identity — so it would hide the failure. currentHeadBuildFailure
    // keys off the current version's own build.
    const value = lifecycle([
      build("b_old", "ready"),
      build("b_new", "failed"),
    ]);
    value.builds[0].sourceVersionId = "sv-old";
    value.builds[1].sourceVersionId = "sv-new";
    value.publishedBuildId = "b_old";
    value.currentVersionId = "sv-new";

    expect(latestFinishedCanvasBuild(value)?.id).toBe("b_old");
    expect(currentHeadBuildFailure(value)?.id).toBe("b_new");
  });

  it("returns null when the current head built fine or is still in flight", () => {
    const value = lifecycle([build("b1", "building")]);
    value.currentVersionId = "sv-1";

    expect(currentHeadBuildFailure(value)).toBeNull();
  });

  it("maps the builds endpoint's snake_case body to the client shape", async () => {
    const fetchMock = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            published_build_id: "b0",
            current_version_id: "sv-1",
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
    const service = new DashboardsService({
      json: async (path: string) => {
        expect(path).toBe("canvases/canvas-1/builds/");
        return (await fetchMock()).json();
      },
    } as unknown as ProjectApiClient);

    const result = await service.getBuilds({ id: "canvas-1" });

    expect(result.publishedBuildId).toBe("b0");
    expect(result.builds[0]).toMatchObject({
      id: "b1",
      sourceVersionId: "sv-1",
      buildStatus: "failed",
    });
    expect(result.builds[0].diagnostics[0].code).toBe("import_not_allowed");
  });
});
