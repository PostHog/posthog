import "reflect-metadata";
import { describe, expect, it, vi } from "vitest";
import type { AuthService } from "../auth/auth";
import { ProjectApiClient } from "../canvas/projectApiClient";
import { SketchpadService } from "./sketchpadService";

describe("SketchpadService", () => {
  it.each([
    [undefined, "sketchpads/"],
    ["space/one?", "sketchpads/?channel=space%2Fone%3F"],
  ])("lists sketchpads for %s", async (channelId, path) => {
    const listPaginated = vi.fn().mockResolvedValue([]);
    const service = new SketchpadService({
      listPaginated,
    } as unknown as ProjectApiClient);
    await expect(service.list(channelId)).resolves.toEqual([]);
    expect(listPaginated).toHaveBeenCalledWith(path, "list sketchpads", {
      limit: 200,
    });
  });

  it.each([204, 400, 403])(
    "updates metadata without a snapshot and handles HTTP %s",
    async (status) => {
      const authenticatedFetch = vi
        .fn()
        .mockResolvedValue(
          new Response(
            status === 204
              ? null
              : JSON.stringify({ detail: "Update refused" }),
            { status },
          ),
        );
      const api = new ProjectApiClient({
        getValidAccessToken: async () => ({ apiHost: "https://example.com" }),
        getState: () => ({ currentProjectId: 1 }),
        authenticatedFetch,
      } as unknown as AuthService);
      const service = new SketchpadService(api);
      const result = service.update("board", {
        name: "Renamed",
        pinned: false,
        channelId: "space",
      });
      if (status === 204) await expect(result).resolves.toBeUndefined();
      else
        await expect(result).rejects.toMatchObject({
          status,
          message: `Failed to update sketchpad (${status}): Update refused`,
        });
      const [, url, request] = authenticatedFetch.mock.calls[0];
      expect(url).toBe("https://example.com/api/projects/1/sketchpads/board/");
      expect(request.method).toBe("PATCH");
      expect(JSON.parse(request.body)).toEqual({
        name: "Renamed",
        pinned: false,
        channel_id: "space",
      });
    },
  );

  it("resolves history sources without changing geometry patches or shared state", async () => {
    const ref = "a".repeat(64);
    const code = "export default () => null";
    const fragment = {
      id: "one",
      x: 0,
      y: 0,
      w: 360,
      h: 240,
      z: 9,
      codeVersion: 7,
      surface: "card",
      hidden: false,
      codeRef: ref,
    };
    const ops = [
      { type: "add_fragment", fragment },
      { type: "update_fragment", id: "one", patch: { x: 12 } },
      {
        type: "update_fragment",
        id: "one",
        patch: { codeRef: ref, codeVersion: 8 },
      },
      { type: "set_state", key: "value", value: { codeRef: "unchanged" } },
      {
        type: "restore",
        toSeq: 1,
        expectedSeq: 4,
        snapshot: { schemaVersion: 1, fragments: [fragment], state: {} },
      },
    ];
    const page = {
      head_seq: ops.length,
      source_versions: { [ref]: code },
      results: ops.map((op, index) => ({
        seq: index + 1,
        op_id: `op-${index}`,
        actor: { kind: "user", user_id: 1 },
        created_at: "2026-01-01T00:00:00Z",
        op,
      })),
    };
    const api = {
      json: vi.fn().mockResolvedValue(page),
    } as unknown as ProjectApiClient;
    const service = new SketchpadService(api);
    const result = await service.opsSince("board", 0);
    const { codeRef: _codeRef, ...resolved } = fragment;
    expect(result.results.map((entry) => entry.op)).toEqual([
      { ...ops[0], fragment: { ...resolved, code } },
      ops[1],
      { ...ops[2], patch: { code, codeVersion: 8 } },
      ops[3],
      {
        ...ops[4],
        snapshot: {
          schemaVersion: 1,
          fragments: [{ ...resolved, code }],
          state: {},
        },
      },
    ]);
    page.source_versions = {};
    await expect(service.opsSince("board", 0)).rejects.toThrow();
  });
});
