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
    });
    expect(rows[0].createdAt).toBe(Date.parse("2026-07-01T00:00:00Z"));
  });
});

describe("DashboardsService.getBuilds", () => {
  it("normalizes the lifecycle payload", async () => {
    const { api } = fakeApi({
      "canvases/c1/builds/?version_id=v1": {
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

    const lifecycle = await service.getBuilds({ id: "c1", versionId: "v1" });

    expect(lifecycle.publishedBuildId).toBe("b1");
    expect(lifecycle.currentVersionId).toBe("v1");
    expect(lifecycle.builds[0].buildStatus).toBe("ready");
  });
});

describe("DashboardsService sharing", () => {
  it("maps the sharing configuration to camelCase", async () => {
    const { api, calls } = fakeApi({
      "canvases/c1/sharing/": {
        enabled: true,
        access_token: "tok",
        password_required: false,
      },
    });
    const service = new DashboardsService(api);

    const sharing = await service.getSharing("c1");

    expect(calls[0].path).toBe("canvases/c1/sharing/");
    expect(sharing).toEqual({
      enabled: true,
      accessToken: "tok",
      passwordRequired: false,
      allowForking: false,
    });
  });

  it("sends the copy permission as a settings patch", async () => {
    const { api, calls } = fakeApi({
      "canvases/c1/sharing/": {
        enabled: true,
        access_token: "tok",
        settings: { allowForking: true },
      },
    });
    const service = new DashboardsService(api);

    const sharing = await service.setSharing({ id: "c1", allowForking: true });

    expect(sharing.allowForking).toBe(true);
    expect(JSON.parse(calls[0].init?.body as string)).toEqual({
      settings: { allowForking: true },
    });
  });

  it("reports a backend without canvas sharing as null instead of throwing", async () => {
    const api = {
      fetch: vi.fn(
        async () =>
          ({ ok: false, status: 404, json: async () => ({}) }) as Response,
      ),
    } as unknown as ProjectApiClient;
    const service = new DashboardsService(api);

    await expect(service.getSharing("c1")).resolves.toBeNull();
  });

  it("patches the enabled flag", async () => {
    const { api, calls } = fakeApi({
      "canvases/c1/sharing/": { enabled: true, access_token: "tok" },
    });
    const service = new DashboardsService(api);

    const sharing = await service.setSharing({ id: "c1", enabled: true });

    expect(sharing.enabled).toBe(true);
    expect(calls[0].init?.method).toBe("PATCH");
    expect(JSON.parse(calls[0].init?.body as string)).toEqual({
      enabled: true,
    });
  });
});

describe("DashboardsService.fork", () => {
  it("posts the source canvas and returns the copy", async () => {
    const { api, calls } = fakeApi({
      "canvases/fork/": apiCanvas({ id: "c2", channel: "personal-1" }),
    });
    const service = new DashboardsService(api);

    const copy = await service.fork("c1");

    expect(copy).toMatchObject({ id: "c2", channelId: "personal-1" });
    expect(JSON.parse(calls[0].init?.body as string)).toEqual({
      source_canvas_id: "c1",
    });
  });
});

describe("DashboardsService.file", () => {
  it("patches the canvas channel", async () => {
    const { api, calls } = fakeApi({
      "canvases/c1/": apiCanvas({ channel: "chan-2" }),
    });
    const service = new DashboardsService(api);

    const canvas = await service.file({ id: "c1", channelId: "chan-2" });

    expect(canvas.channelId).toBe("chan-2");
    expect(calls[0]).toMatchObject({ path: "canvases/c1/" });
    expect(JSON.parse(calls[0].init?.body as string)).toEqual({
      channel_id: "chan-2",
    });
  });
});
