import { describe, expect, it, vi } from "vitest";
import { DashboardsService } from "./dashboardsService";
import type { DesktopFsClient, FsEntryBase } from "./desktopFsClient";

// ensureHomeCanvas fetches the signed-in user's label via posthogApi; stub it so
// the service doesn't reach the network in tests.
vi.mock("./posthogApi", () => ({
  fetchCurrentUser: vi.fn(async () => ({ label: "Tester" })),
}));

// A dashboard FS row carrying our payload under `meta`, as the backend returns it.
function dashboardRow(
  id: string,
  name: string,
  channelId: string,
  updatedAt: number,
): FsEntryBase & { meta: Record<string, unknown> } {
  return {
    id,
    path: `Channels/${channelId}/${name}`,
    type: "dashboard",
    meta: { channelId, updatedAt, templateId: "dashboard", spec: null },
  };
}

// A fake DesktopFsClient exposing only the two methods `list` touches:
// getEntry (to resolve the channel folder path) and listByQuery (the filtered
// fetch). listByQuery is declared with explicit params so spy calls carry args.
function fakeFs(rows: FsEntryBase[]) {
  const listByQuery = vi.fn(
    async (_query: string, _errorLabel: string): Promise<FsEntryBase[]> => rows,
  );
  const fs = {
    getEntry: async (id: string) => ({ id, path: `Channels/${id}` }),
    listByQuery,
  };
  return { fs: fs as unknown as DesktopFsClient, listByQuery };
}

describe("DashboardsService.list", () => {
  it("fetches with a parent-scoped, type-filtered query", async () => {
    const { fs, listByQuery } = fakeFs([]);
    const service = new DashboardsService(fs, {} as never);

    await service.list("chan-1");

    expect(listByQuery).toHaveBeenCalledTimes(1);
    const [query] = listByQuery.mock.calls[0];
    expect(query).toContain("parent=");
    expect(query).toContain(encodeURIComponent("Channels/chan-1"));
    expect(query).toContain("type=dashboard");
  });

  it("maps rows to summaries sorted by updatedAt descending", async () => {
    const { fs } = fakeFs([
      dashboardRow("a", "Older", "chan-1", 100),
      dashboardRow("b", "Newer", "chan-1", 300),
      dashboardRow("c", "Middle", "chan-1", 200),
    ]);
    const service = new DashboardsService(fs, {} as never);

    const result = await service.list("chan-1");

    expect(result.map((d) => d.id)).toEqual(["b", "c", "a"]);
    expect(result[0]).toMatchObject({ name: "Newer", channelId: "chan-1" });
  });
});

// Fake exposing getEntry (resolves the row to rename) + fetch (the PATCH).
function fakeFsForRename(entry: FsEntryBase) {
  const fetch = vi.fn(async (_path: string, init?: RequestInit) => ({
    ok: true,
    status: 200,
    json: async () => ({
      ...entry,
      path: JSON.parse((init?.body as string) ?? "{}").path ?? entry.path,
    }),
  }));
  const fs = {
    getEntry: async () => entry,
    fetch,
  };
  return { fs: fs as unknown as DesktopFsClient, fetch };
}

describe("DashboardsService.rename", () => {
  it("PATCHes a new last path segment built from the name", async () => {
    const entry = dashboardRow("d1", "Untitled canvas", "chan-1", 100);
    const { fs, fetch } = fakeFsForRename(entry);
    const service = new DashboardsService(fs, {} as never);

    const result = await service.rename({ id: "d1", name: "Churn by plan" });

    expect(fetch).toHaveBeenCalledTimes(1);
    const [, init] = fetch.mock.calls[0];
    expect(init?.method).toBe("PATCH");
    expect(JSON.parse((init?.body as string) ?? "{}").path).toBe(
      "Channels/chan-1/Churn by plan",
    );
    expect(result.name).toBe("Churn by plan");
  });

  it("no-ops (no fetch) when the name resolves to the same path", async () => {
    const entry = dashboardRow("d1", "Same name", "chan-1", 100);
    const { fs, fetch } = fakeFsForRename(entry);
    const service = new DashboardsService(fs, {} as never);

    const result = await service.rename({ id: "d1", name: "Same name" });

    expect(fetch).not.toHaveBeenCalled();
    expect(result.name).toBe("Same name");
  });
});

// A stateful fake exposing getEntry + fetch, enough for create/saveFreeform/PATCH.
// POST "" assigns an id and stores the row; PATCH "<id>/" merges meta/path.
function statefulFs(initial: Record<string, Record<string, unknown>>) {
  const entries: Record<string, Record<string, unknown>> = { ...initial };
  let seq = 0;
  const fetch = vi.fn(
    async (suffix: string, init?: { method?: string; body?: string }) => {
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(init.body) : undefined;
      if (suffix === "" && method === "POST") {
        const id = `new-${++seq}`;
        const entry = {
          id,
          path: body.path,
          type: body.type,
          meta: body.meta ?? {},
        };
        entries[id] = entry;
        return { ok: true, status: 200, json: async () => entry } as Response;
      }
      const id = decodeURIComponent(suffix.replace(/\/$/, ""));
      const prev = entries[id] ?? { id, path: "", meta: {} };
      const next = { ...prev };
      if (body?.meta) next.meta = body.meta;
      if (body?.path) next.path = body.path;
      entries[id] = next;
      return { ok: true, status: 200, json: async () => next } as Response;
    },
  );
  const getEntry = vi.fn(async (id: string) => entries[id] ?? null);
  const fs = { getEntry, fetch } as unknown as DesktopFsClient;
  return { fs, fetch, entries };
}

describe("DashboardsService.ensureHomeCanvas", () => {
  it("creates + seeds a freeform canvas and records it on the channel folder", async () => {
    const { fs, entries } = statefulFs({
      "chan-1": {
        id: "chan-1",
        path: "marketing",
        type: "folder",
        meta: {},
      },
    });
    const service = new DashboardsService(fs, {} as never);

    const record = await service.ensureHomeCanvas("chan-1");

    // The freeform canvas was created under the channel folder.
    expect(record.id).toBe("new-1");
    expect(record.templateId).toBe("freeform");
    expect(entries["new-1"]?.path).toBe("marketing/Home");

    // Its seeded source queries the file_system system table and bakes both ids.
    const meta = entries["new-1"]?.meta as { code?: string };
    expect(meta.code).toContain("system.file_system");
    expect(meta.code).toContain("chan-1");
    expect(meta.code).toContain("new-1");

    // The channel folder now points at the home canvas.
    const folderMeta = entries["chan-1"]?.meta as { homeCanvasId?: string };
    expect(folderMeta.homeCanvasId).toBe("new-1");
  });

  it("seeds source that transpiles as valid TSX", async () => {
    const { fs, entries } = statefulFs({
      "chan-1": { id: "chan-1", path: "marketing", type: "folder", meta: {} },
    });
    const service = new DashboardsService(fs, {} as never);

    await service.ensureHomeCanvas("chan-1");
    const code = (entries["new-1"]?.meta as { code?: string }).code ?? "";

    // The sandbox transpiles the seeded code with Babel at runtime; mirror that
    // here with esbuild so a syntax error is caught in CI, not in the iframe.
    const { transform } = await import("esbuild");
    await expect(
      transform(code, { loader: "tsx", format: "esm" }),
    ).resolves.toBeDefined();
  });

  it("is idempotent: returns the existing home canvas without creating another", async () => {
    const { fs, fetch, entries } = statefulFs({
      "chan-1": {
        id: "chan-1",
        path: "marketing",
        type: "folder",
        meta: { homeCanvasId: "home-x" },
      },
      "home-x": {
        id: "home-x",
        path: "marketing/Home",
        type: "dashboard",
        meta: {
          channelId: "chan-1",
          templateId: "freeform",
          code: "// seeded",
        },
      },
    });
    const service = new DashboardsService(fs, {} as never);

    const record = await service.ensureHomeCanvas("chan-1");

    expect(record.id).toBe("home-x");
    // No create/patch happened — the folder already had a live home canvas.
    expect(fetch).not.toHaveBeenCalled();
    expect(Object.keys(entries)).toEqual(["chan-1", "home-x"]);
  });
});

describe("DashboardsService.resetHomeCanvas", () => {
  it("appends a fresh default version without dropping history", async () => {
    const { fs, entries } = statefulFs({
      "chan-1": {
        id: "chan-1",
        path: "marketing",
        type: "folder",
        meta: { homeCanvasId: "home-x" },
      },
      "home-x": {
        id: "home-x",
        path: "marketing/Home",
        type: "dashboard",
        meta: {
          channelId: "chan-1",
          templateId: "freeform",
          code: "// edited by the user",
          versions: [{ id: "v1", code: "// edited by the user", createdAt: 1 }],
          currentVersionId: "v1",
        },
      },
    });
    const service = new DashboardsService(fs, {} as never);

    const record = await service.resetHomeCanvas("chan-1");

    // The returned record carries the regenerated default source (queries the
    // file_system table and bakes both ids), not the user's edit.
    expect(record.id).toBe("home-x");
    expect(record.code).toContain("system.file_system");
    expect(record.code).toContain("chan-1");
    expect(record.code).toContain("home-x");
    expect(record.code).not.toContain("// edited by the user");

    // History is preserved: the prior version stays and the default is appended
    // as the new head, so Undo can restore the user's edit.
    expect(record.versions?.map((v) => v.id)).toEqual([
      "v1",
      record.currentVersionId,
    ]);
    expect(record.currentVersionId).not.toBe("v1");
    expect(record.versions?.at(-1)?.code).toBe(record.code);

    // Persisted to the same canvas (no new canvas created).
    expect(Object.keys(entries)).toEqual(["chan-1", "home-x"]);
  });

  it("creates a home canvas if the channel has none yet", async () => {
    const { fs, entries } = statefulFs({
      "chan-1": { id: "chan-1", path: "marketing", type: "folder", meta: {} },
    });
    const service = new DashboardsService(fs, {} as never);

    const record = await service.resetHomeCanvas("chan-1");

    expect(record.id).toBe("new-1");
    expect(record.code).toContain("system.file_system");
    expect(
      (entries["chan-1"]?.meta as { homeCanvasId?: string }).homeCanvasId,
    ).toBe("new-1");
  });
});
