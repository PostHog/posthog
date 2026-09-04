import {
  type CanvasV2AppendOpsInput,
  type CanvasV2AppendOpsResult,
  type CanvasV2Board,
  type CanvasV2BoardSummary,
  type CanvasV2OpsPage,
  canvasV2BoardSchema,
  canvasV2BoardSummarySchema,
  canvasV2FragmentSchema,
  canvasV2SnapshotSchema,
} from "@posthog/shared";
import { inject, injectable } from "inversify";
import { z } from "zod";
import {
  PROJECT_API_CLIENT,
  type ProjectApiClient,
} from "../canvas/projectApiClient";
import {
  canvasV2AppendOpsResultSchema,
  canvasV2OpsPageSchema,
} from "./canvasV2Schemas";
import type { ICanvasV2BoardsService } from "./identifiers";

const DEFAULT_OPS_PAGE_SIZE = 500;

interface ApiActor {
  kind: string;
  user_id?: number | null;
  user_uuid?: string | null;
  user_name?: string | null;
  user_email?: string | null;
  task_id?: string | null;
}

interface ApiLogEntry {
  seq: number;
  op_id: string;
  actor: ApiActor;
  created_at: string;
  op: unknown;
}

interface ApiBoard {
  id: string;
  name: string;
  channel: string;
  created_at: string;
  updated_at: string;
  created_by: ApiActor | null;
  head_seq: number;
  snapshot: unknown;
  snapshot_seq: number;
  server_snapshots?: boolean;
  source_versions?: Record<string, string>;
  ops_after_snapshot: ApiLogEntry[];
}

interface ApiBoardSummary {
  id: string;
  name: string;
  channel: string;
  created_at: string;
  updated_at: string;
  head_seq: number;
  fragment_count: number;
  pinned?: boolean;
  created_by?: ApiActor | null;
  last_actor?: ApiActor | null;
  preview?: { x: number; y: number; w: number; h: number }[];
}

interface ApiOpsPage {
  results: ApiLogEntry[];
  head_seq: number;
}

interface ApiAppendOpsResult {
  results: { op_id: string; seq: number }[];
  replayed?: ApiLogEntry[];
  head_seq: number;
}

function actorInput(actor: ApiActor): unknown {
  return {
    kind: actor.kind,
    userId: actor.user_id ?? undefined,
    userUuid: actor.user_uuid ?? undefined,
    userName: actor.user_name ?? undefined,
    userEmail: actor.user_email ?? undefined,
    taskId: actor.task_id ?? undefined,
  };
}

function logEntryInput(entry: ApiLogEntry): unknown {
  return {
    seq: entry.seq,
    opId: entry.op_id,
    actor: actorInput(entry.actor),
    createdAt: entry.created_at,
    op: entry.op,
  };
}

const compactSnapshotSchema = canvasV2SnapshotSchema.extend({
  fragments: z.array(
    canvasV2FragmentSchema
      .omit({ code: true })
      .extend({ codeRef: z.string().length(64) }),
  ),
});

function boardInput(api: ApiBoard): unknown {
  let snapshot = api.snapshot;
  if (api.source_versions) {
    const compact = compactSnapshotSchema.parse(snapshot);
    const sources = api.source_versions;
    snapshot = {
      ...compact,
      fragments: compact.fragments.map(({ codeRef, ...fragment }) => ({
        ...fragment,
        code: sources[codeRef],
      })),
    };
  }
  return {
    id: api.id,
    name: api.name,
    channelId: api.channel,
    createdAt: api.created_at,
    updatedAt: api.updated_at,
    createdBy: api.created_by ? actorInput(api.created_by) : undefined,
    headSeq: api.head_seq,
    snapshot,
    snapshotSeq: api.snapshot_seq,
    serverSnapshots: api.server_snapshots,
    opsAfterSnapshot: (api.ops_after_snapshot ?? []).map(logEntryInput),
  };
}

function boardPath(id: string): string {
  return `canvas_boards/${encodeURIComponent(id)}/`;
}

/**
 * Canvas v2 boards, backed by the project's canvas_boards API. A board is a
 * snapshot plus an append-only op log; this service moves both across the
 * wire and maps the snake_case backend fields to the shared camelCase types.
 */
@injectable()
export class CanvasV2BoardsService implements ICanvasV2BoardsService {
  constructor(
    @inject(PROJECT_API_CLIENT)
    private readonly api: ProjectApiClient,
  ) {}

  async list(channelId: string): Promise<CanvasV2BoardSummary[]> {
    return this.listBoards(
      `canvas_boards/?channel=${encodeURIComponent(channelId)}`,
    );
  }

  async listAll(): Promise<CanvasV2BoardSummary[]> {
    return this.listBoards("canvas_boards/");
  }

  private async listBoards(path: string): Promise<CanvasV2BoardSummary[]> {
    const rows = await this.api.listPaginated<ApiBoardSummary>(
      path,
      "list canvas boards",
      { limit: 200 },
    );
    return rows.map((row) =>
      canvasV2BoardSummarySchema.parse({
        id: row.id,
        name: row.name,
        channelId: row.channel,
        createdAt: row.created_at,
        updatedAt: row.updated_at,
        headSeq: row.head_seq,
        fragmentCount: row.fragment_count,
        pinned: row.pinned ?? false,
        createdBy: row.created_by ? actorInput(row.created_by) : undefined,
        lastActor: row.last_actor ? actorInput(row.last_actor) : undefined,
        preview: row.preview ?? [],
      }),
    );
  }

  async get(id: string): Promise<CanvasV2Board> {
    const api = await this.api.json<ApiBoard>(
      `${boardPath(id)}?compact=true`,
      "load canvas board",
    );
    return canvasV2BoardSchema.parse(boardInput(api));
  }

  async create(channelId: string, name: string): Promise<CanvasV2Board> {
    const api = await this.api.json<ApiBoard>(
      "canvas_boards/",
      "create canvas board",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, channel_id: channelId }),
      },
    );
    return canvasV2BoardSchema.parse(boardInput(api));
  }

  setChannel(id: string, channelId: string): Promise<CanvasV2Board> {
    return this.patch(id, { channel_id: channelId }, "file canvas board");
  }

  setPinned(id: string, pinned: boolean): Promise<CanvasV2Board> {
    return this.patch(id, { pinned }, "pin canvas board");
  }

  rename(id: string, name: string): Promise<CanvasV2Board> {
    return this.patch(id, { name }, "rename canvas board");
  }

  private async patch(
    id: string,
    body: Record<string, unknown>,
    errorLabel: string,
  ): Promise<CanvasV2Board> {
    const api = await this.api.json<ApiBoard>(boardPath(id), errorLabel, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    return canvasV2BoardSchema.parse(boardInput(api));
  }

  async remove(id: string): Promise<void> {
    const res = await this.api.fetch(boardPath(id), { method: "DELETE" });
    // Already gone is a successful delete; surface anything else.
    if (!res.ok && res.status !== 404) {
      throw new Error(`Failed to delete canvas board (${res.status})`);
    }
  }

  async opsSince(
    id: string,
    since: number,
    limit = DEFAULT_OPS_PAGE_SIZE,
  ): Promise<CanvasV2OpsPage> {
    const api = await this.api.json<ApiOpsPage>(
      `${boardPath(id)}ops/?since=${since}&limit=${limit}`,
      "load canvas board ops",
    );
    return canvasV2OpsPageSchema.parse({
      results: (api.results ?? []).map(logEntryInput),
      headSeq: api.head_seq,
    });
  }

  async appendOps(
    id: string,
    input: CanvasV2AppendOpsInput,
  ): Promise<CanvasV2AppendOpsResult> {
    const api = await this.api.json<ApiAppendOpsResult>(
      `${boardPath(id)}ops/`,
      "append canvas board ops",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ops: input.ops.map((draft) => ({
            op_id: draft.opId,
            op: draft.op,
          })),
          actor: { kind: input.actor.kind, task_id: input.actor.taskId },
          base_seq: input.baseSeq,
          snapshot: input.snapshot,
        }),
      },
    );
    return canvasV2AppendOpsResultSchema.parse({
      replayed: (api.replayed ?? []).map(logEntryInput),
      results: (api.results ?? []).map((result) => ({
        opId: result.op_id,
        seq: result.seq,
      })),
      headSeq: api.head_seq,
    });
  }
}
