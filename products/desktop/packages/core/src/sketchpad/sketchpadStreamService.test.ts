import "reflect-metadata";
import { describe, expect, it, vi } from "vitest";
import type { ProjectApiClient } from "../canvas/projectApiClient";
import { SketchpadStreamService } from "./sketchpadStreamService";

describe("SketchpadStreamService", () => {
  it("skips invalid operations and maps the next valid operation", async () => {
    const row = {
      seq: 1,
      op_id: "op-1",
      actor: { kind: "user", user_id: 2, user_name: "Test User" },
      created_at: "2026-01-01T00:00:00Z",
      op: { type: "set_state", key: "count", value: 1 },
    };
    const body = [
      null,
      1,
      {},
      { ...row, actor: null },
      { ...row, actor: "user" },
      row,
    ]
      .map((value) => `event: op\ndata: ${JSON.stringify(value)}\n\n`)
      .join("");
    const service = new SketchpadStreamService({
      fetch: vi.fn().mockResolvedValue(new Response(body)),
    } as unknown as ProjectApiClient);
    const stream = service.streamSketchpad("board");
    try {
      expect((await stream.next()).value).toEqual({ type: "live", live: true });
      expect((await stream.next()).value).toEqual({
        type: "op",
        entry: {
          seq: 1,
          opId: "op-1",
          actor: { kind: "user", userId: 2, userName: "Test User" },
          createdAt: row.created_at,
          op: row.op,
        },
      });
    } finally {
      await stream.return(undefined);
    }
  });
});
