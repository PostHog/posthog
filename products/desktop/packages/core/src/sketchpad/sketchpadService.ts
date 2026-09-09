import {
  type Sketchpad,
  type SketchpadAppendOpsInput,
  type SketchpadAppendOpsResult,
  type SketchpadCompiledFragment,
  type SketchpadOpsPage,
  type SketchpadSummary,
  sketchpadActorSchema,
  sketchpadAppendOpsResultSchema,
  sketchpadCompiledResultsSchema,
  sketchpadFragmentSchema,
  sketchpadLogEntrySchema,
  sketchpadOpSchema,
  sketchpadOpsPageSchema,
  sketchpadSchema,
  sketchpadSnapshotSchema,
  sketchpadSummarySchema,
} from "@posthog/shared";
import { inject, injectable } from "inversify";
import { z } from "zod";
import {
  PROJECT_API_CLIENT,
  type ProjectApiClient,
} from "../canvas/projectApiClient";
import type { ISketchpadService } from "./identifiers";
import type { SketchpadMetadataPatch } from "./sketchpadSchemas";

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

interface ApiSketchpad {
  id: string;
  name: string;
  channel: string;
  created_at: string;
  updated_at: string;
  created_by: ApiActor | null;
  head_seq: number;
  history_start_seq: number;
  history_snapshot: unknown;
  snapshot: unknown;
  source_versions: Record<string, string>;
}

interface ApiSketchpadSummary {
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
  history_start_seq: number;
  history_snapshot: unknown;
  source_versions: Record<string, string>;
}

interface ApiAppendOpsResult {
  results: { op_id: string; seq: number }[];
  replayed?: ApiLogEntry[];
  head_seq: number;
}

function actorInput(actor: ApiActor): z.input<typeof sketchpadActorSchema> {
  return sketchpadActorSchema.parse({
    kind: actor.kind,
    userId: actor.user_id ?? undefined,
    userUuid: actor.user_uuid ?? undefined,
    userName: actor.user_name ?? undefined,
    userEmail: actor.user_email ?? undefined,
    taskId: actor.task_id ?? undefined,
  });
}

export function logEntryInput(
  value: unknown,
): z.output<typeof sketchpadLogEntrySchema> {
  if (typeof value !== "object" || value === null)
    return sketchpadLogEntrySchema.parse(value);
  const entry = value as Record<string, unknown>;
  const actor = entry.actor;
  return sketchpadLogEntrySchema.parse({
    seq: entry.seq,
    opId: entry.op_id,
    actor:
      typeof actor === "object" && actor !== null
        ? actorInput(actor as ApiActor)
        : actor,
    createdAt: entry.created_at,
    op: entry.op,
  });
}

const compactSnapshotSchema = sketchpadSnapshotSchema.extend({
  fragments: z.array(
    sketchpadFragmentSchema
      .omit({ code: true })
      .extend({ codeRef: z.string().length(64) }),
  ),
});

const sourcePatchSchema = z
  .object({ codeRef: z.string().length(64).optional() })
  .passthrough();

function sourceInput(
  value: unknown,
  sources: Record<string, string>,
): Record<string, unknown> {
  const { codeRef, ...fragment } = sourcePatchSchema.parse(value);
  return codeRef
    ? { ...fragment, code: z.string().parse(sources[codeRef]) }
    : fragment;
}

function snapshotInput(
  value: unknown,
  sources: Record<string, string>,
): z.input<typeof sketchpadSnapshotSchema> {
  const compact = compactSnapshotSchema.parse(value);
  return {
    ...compact,
    fragments: compact.fragments.map((fragment) =>
      sketchpadFragmentSchema.parse(sourceInput(fragment, sources)),
    ),
  };
}

function opInput(
  value: unknown,
  sources: Record<string, string>,
): z.input<typeof sketchpadOpSchema> {
  const op = z.object({ type: z.string() }).passthrough().parse(value);
  if (op.type === "add_fragment")
    return sketchpadOpSchema.parse({
      ...op,
      fragment: sourceInput(op.fragment, sources),
    });
  if (op.type === "update_fragment")
    return sketchpadOpSchema.parse({
      ...op,
      patch: sourceInput(op.patch, sources),
    });
  if (op.type === "restore")
    return sketchpadOpSchema.parse({
      ...op,
      snapshot: snapshotInput(op.snapshot, sources),
    });
  return sketchpadOpSchema.parse(op);
}

function sketchpadInput(api: ApiSketchpad): z.input<typeof sketchpadSchema> {
  return {
    id: api.id,
    name: api.name,
    channelId: api.channel,
    createdAt: api.created_at,
    updatedAt: api.updated_at,
    createdBy: api.created_by ? actorInput(api.created_by) : undefined,
    headSeq: api.head_seq,
    historyStartSeq: api.history_start_seq,
    historySnapshot: snapshotInput(api.history_snapshot, api.source_versions),
    snapshot: snapshotInput(api.snapshot, api.source_versions),
  };
}

export function sketchpadPath(id: string): string {
  return `sketchpads/${encodeURIComponent(id)}/`;
}

@injectable()
export class SketchpadService implements ISketchpadService {
  constructor(
    @inject(PROJECT_API_CLIENT)
    private readonly api: ProjectApiClient,
  ) {}

  async compiled(
    id: string,
    refs: string[],
    signal?: AbortSignal,
  ): Promise<Record<string, SketchpadCompiledFragment>> {
    const response = await this.api.json<{ results: unknown }>(
      `${sketchpadPath(id)}compiled/`,
      "load compiled fragments",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refs }),
        signal,
      },
    );
    return sketchpadCompiledResultsSchema.parse(response.results);
  }

  async list(channelId?: string): Promise<SketchpadSummary[]> {
    const rows = await this.api.listPaginated<ApiSketchpadSummary>(
      channelId === undefined
        ? "sketchpads/"
        : `sketchpads/?channel=${encodeURIComponent(channelId)}`,
      "list sketchpads",
      { limit: 200 },
    );
    return rows.map((row) =>
      sketchpadSummarySchema.parse({
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

  async get(id: string): Promise<Sketchpad> {
    const api = await this.api.json<ApiSketchpad>(
      sketchpadPath(id),
      "load sketchpad",
    );
    return sketchpadSchema.parse(sketchpadInput(api));
  }

  async create(channelId: string, name: string): Promise<Sketchpad> {
    const api = await this.api.json<ApiSketchpad>(
      "sketchpads/",
      "create sketchpad",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, channel_id: channelId }),
      },
    );
    return sketchpadSchema.parse(sketchpadInput(api));
  }

  async update(
    id: string,
    { channelId, ...patch }: SketchpadMetadataPatch,
  ): Promise<void> {
    await this.api.request(sketchpadPath(id), "update sketchpad", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...patch, channel_id: channelId }),
    });
  }

  async remove(id: string): Promise<void> {
    const res = await this.api.fetch(sketchpadPath(id), { method: "DELETE" });
    if (!res.ok && res.status !== 404) {
      throw new Error(`Failed to delete sketchpad (${res.status})`);
    }
  }

  async opsSince(
    id: string,
    since: number,
    limit = DEFAULT_OPS_PAGE_SIZE,
  ): Promise<SketchpadOpsPage> {
    const api = await this.api.json<ApiOpsPage>(
      `${sketchpadPath(id)}ops/?since=${since}&limit=${limit}`,
      "load sketchpad ops",
    );
    return sketchpadOpsPageSchema.parse({
      results: (api.results ?? []).map((entry) =>
        logEntryInput({ ...entry, op: opInput(entry.op, api.source_versions) }),
      ),
      headSeq: api.head_seq,
      historyStartSeq: api.history_start_seq,
      historySnapshot: snapshotInput(api.history_snapshot, api.source_versions),
    });
  }

  async appendOps(
    id: string,
    input: SketchpadAppendOpsInput,
  ): Promise<SketchpadAppendOpsResult> {
    const api = await this.api.json<ApiAppendOpsResult>(
      `${sketchpadPath(id)}ops/`,
      "append sketchpad ops",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          base_seq: input.baseSeq,
          ops: input.ops.map((draft) => ({
            op_id: draft.opId,
            op: draft.op,
          })),
          actor: { kind: input.actor.kind, task_id: input.actor.taskId },
        }),
      },
    );
    return sketchpadAppendOpsResultSchema.parse({
      replayed: (api.replayed ?? []).map(logEntryInput),
      results: (api.results ?? []).map((result) => ({
        opId: result.op_id,
        seq: result.seq,
      })),
      headSeq: api.head_seq,
    });
  }
}
