import { transform } from "esbuild";
import { describe, expect, it, vi } from "vitest";
import { DashboardsService } from "./dashboardsService";
import type { ProjectApiClient } from "./projectApiClient";

// A canvas as the PostHog canvases API returns it.
function apiCanvas(overrides: Record<string, unknown> = {}) {
  return {
    id: "c1",
    name: "Revenue board",
    channel: "chan-1",
    template_id: "freeform",
    context: "",
    generation_task_id: null,
    pinned_at: null,
    is_home: false,
    current_version_id: "v1",
    published_build_id: null,
    created_by: { first_name: "Ada", last_name: "L", email: "ada@x.com" },
    created_at: "2026-07-01T00:00:00Z",
    updated_at: "2026-07-02T00:00:00Z",
    ...overrides,
  };
}

// A fake ProjectApiClient recording calls; per-path handlers return payloads.
function fakeApi(
  handlers: Record<string, unknown | ((init?: RequestInit) => unknown)>,
) {
  const calls: { path: string; init?: RequestInit }[] = [];
  const resolve = (path: string, init?: RequestInit) => {
    calls.push({ path, init });
    const key = Object.keys(handlers).find((prefix) => path.startsWith(prefix));
    if (key === undefined) throw new Error(`Unhandled path: ${path}`);
    const handler = handlers[key];
    return typeof handler === "function"
      ? (handler as (init?: RequestInit) => unknown)(init)
      : handler;
  };
  const api = {
    json: vi.fn(async (path: string, _label: string, init?: RequestInit) =>
      resolve(path, init),
    ),
    listPaginated: vi.fn(async (path: string) => resolve(path) as unknown[]),
    fetch: vi.fn(async (path: string, init?: RequestInit) => {
      const body = resolve(path, init);
      return {
        ok: true,
        status: 200,
        json: async () => body,
      } as unknown as Response;
    }),
  };
  return { api: api as unknown as ProjectApiClient, calls };
}

describe("DashboardsService.list", () => {
  it("maps API canvases to camelCase records", async () => {
    const { api, calls } = fakeApi({
      "canvases/?channel=chan-1": [apiCanvas()],
    });
    const service = new DashboardsService(api);

    const rows = await service.list("chan-1");

    expect(calls[0].path).toBe("canvases/?channel=chan-1");
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({
      id: "c1",
      channelId: "chan-1",
      name: "Revenue board",
      createdBy: "Ada L",
      currentVersionId: "v1",
      isHome: false,
    });
    expect(rows[0].createdAt).toBe(Date.parse("2026-07-01T00:00:00Z"));
  });
});

describe("DashboardsService.ensureHomeCanvas", () => {
  it("returns an existing seeded home canvas without creating another", async () => {
    const home = apiCanvas({
      id: "home-1",
      is_home: true,
      current_version_id: "v9",
    });
    const { api, calls } = fakeApi({
      "canvases/?channel=chan-1&is_home=true": [home],
    });
    const service = new DashboardsService(api);

    const record = await service.ensureHomeCanvas("chan-1");

    expect(record.id).toBe("home-1");
    expect(
      calls.every((call) => !call.init || call.init.method === undefined),
    ).toBe(true);
  });

  it("creates and publish-seeds a home canvas when the channel has none", async () => {
    const created = apiCanvas({
      id: "home-1",
      is_home: true,
      current_version_id: null,
    });
    let published: Record<string, unknown> | null = null;
    const { api } = fakeApi({
      "canvases/?channel=chan-1&is_home=true": [],
      "canvases/home-1/publish/": (init?: RequestInit) => {
        published = JSON.parse(String(init?.body));
        return { current_version_id: "v1" };
      },
      "canvases/home-1/": apiCanvas({
        id: "home-1",
        is_home: true,
        current_version_id: "v1",
      }),
      "canvases/": created,
    });
    const service = new DashboardsService(api);

    const record = await service.ensureHomeCanvas("chan-1");

    expect(record.currentVersionId).toBe("v1");
    expect(published).not.toBeNull();
    const payload = published as unknown as {
      project: {
        files: Record<string, string>;
        capabilities: { posthog: { inlineQueries: boolean } };
      };
      expected_current_version_id: string | null;
    };
    // The board queries system tables ad hoc, so the capability must be
    // declared or view mode rejects every data request.
    expect(payload.project.capabilities.posthog.inlineQueries).toBe(true);
    expect(payload.expected_current_version_id).toBeNull();
    expect(payload.project.files["src/canvas.tsx"]).toContain(
      "system.canvases",
    );
    expect(payload.project.files["src/canvas.tsx"]).toContain("system.tasks");
  });

  it("seeds source that transpiles as valid TSX", async () => {
    const { api } = fakeApi({
      "canvases/?channel=chan-1&is_home=true": [],
      "canvases/home-1/publish/": { current_version_id: "v1" },
      "canvases/home-1/": apiCanvas({
        id: "home-1",
        is_home: true,
        current_version_id: "v1",
      }),
      "canvases/": apiCanvas({
        id: "home-1",
        is_home: true,
        current_version_id: null,
      }),
    });
    const service = new DashboardsService(api);

    await service.ensureHomeCanvas("chan-1");

    const publish = (api.json as ReturnType<typeof vi.fn>).mock.calls.find(
      ([path]) => String(path).endsWith("/publish/"),
    );
    expect(publish).toBeDefined();
    const body = JSON.parse(String(publish?.[2]?.body)) as {
      project: { files: Record<string, string> };
    };
    await expect(
      transform(body.project.files["src/canvas.tsx"], { loader: "tsx" }),
    ).resolves.toBeDefined();
  });
});

describe("DashboardsService.resetHomeCanvas", () => {
  it("publishes a fresh default guarded on the current head", async () => {
    const home = apiCanvas({
      id: "home-1",
      is_home: true,
      current_version_id: "v3",
    });
    let published: Record<string, unknown> | null = null;
    const { api } = fakeApi({
      "canvases/?channel=chan-1&is_home=true": [home],
      "canvases/home-1/publish/": (init?: RequestInit) => {
        published = JSON.parse(String(init?.body));
        return { current_version_id: "v4" };
      },
      "canvases/home-1/": apiCanvas({
        id: "home-1",
        is_home: true,
        current_version_id: "v4",
      }),
    });
    const service = new DashboardsService(api);

    const record = await service.resetHomeCanvas("chan-1");

    expect(record.currentVersionId).toBe("v4");
    expect(
      (published as unknown as { expected_current_version_id: string | null })
        ?.expected_current_version_id,
    ).toBe("v3");
  });
});

describe("DashboardsService.getBuilds", () => {
  it("normalizes the lifecycle payload", async () => {
    const { api } = fakeApi({
      "canvases/c1/builds/": {
        published_build_id: "b1",
        current_version_id: "v1",
        builds: [
          {
            id: "b1",
            source_version_id: "v1",
            build_status: "ready",
            diagnostics: [],
            manifest: null,
            artifact_url: null,
            pinned: false,
            created_at: "2026-07-01T00:00:00Z",
            finished_at: null,
          },
        ],
      },
    });
    const service = new DashboardsService(api);

    const lifecycle = await service.getBuilds("c1");

    expect(lifecycle.publishedBuildId).toBe("b1");
    expect(lifecycle.currentVersionId).toBe("v1");
    expect(lifecycle.builds[0].buildStatus).toBe("ready");
  });
});
