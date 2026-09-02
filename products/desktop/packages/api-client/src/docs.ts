// Hand-written client surface for the Docs API
// (`/api/projects/{project_id}/docs/`), mirroring the shape
// typed-openapi emits in `generated.ts`. The docs routes are not in the OpenAPI
// snapshot `generated.ts` was built from, so this module fills the gap by hand;
// once `apps/code/scripts/update-openapi-client.ts` is rerun against a schema
// that includes them, `Schemas.Doc` and friends land in `generated.ts` and this
// file can be deleted in favor of the generated equivalents.
import { ApiRequestError } from "./fetcher";
import type { ApiClient, Method } from "./generated";

export namespace DocSchemas {
  export type DocStatus = "draft" | "active" | "done";
  /** A page the space writes, or the one doc that is the space's context notes. */
  export type DocKind = "page" | "context";
  export type DocTemplate = "blank" | "notes";

  export interface DocPerson {
    id: number;
    uuid: string;
    first_name: string;
    last_name: string;
    email: string;
  }

  /** A ProseMirror node tree. Nothing outside the editor reads into it. */
  export type ProseMirrorDoc = Record<string, unknown>;

  export interface DocSummary {
    id: string;
    channel_id: string;
    title: string;
    status: DocStatus;
    kind: DocKind;
    position: number;
    version: number;
    created_by: DocPerson | null;
    created_at: string;
    updated_at: string;
    /** The first words of the page. Filled on the space home only. */
    excerpt: string;
    open_thread_count: number;
    watch_count: number;
  }

  /** A section under watch, as the space's context page lists it. */
  export interface WatchSummary {
    doc_id: string;
    doc_title: string;
    anchor_key: string;
    anchor_text: string;
    loop_id: string | null;
    last_report: string;
    last_report_at: string | null;
    created_at: string;
  }

  export interface Doc extends DocSummary {
    content: ProseMirrorDoc | null;
    text_content: string;
  }

  export type PostAuthorKind = "human" | "agent" | "system";
  /** A thread hangs off a phrase, a data point the page asked for, or a section the agent keeps checking. */
  export type DiscussionKind = "text" | "data" | "watch";
  export type AgentDelivery = "not_requested" | "sent" | "no_run" | "failed";

  export interface DiscussionPost {
    id: string;
    content: string;
    /** Null for the agent and for a system line. */
    created_by: DocPerson | null;
    created_at: string;
    author_kind: PostAuthorKind;
    sent_to_agent: boolean;
  }

  /** The query behind a data point. The page runs it on every read. */
  export interface DataAnswer {
    query: string;
    label: string;
    note: string;
    run_id: string | null;
    updated_at: string | null;
  }

  export interface DiscussionThread extends DiscussionPost {
    anchor_key: string;
    anchor_text: string;
    resolved: boolean;
    kind: DiscussionKind;
    /** The agent task this thread talks to, once someone tagged the agent. */
    task_id: string | null;
    /** The loop behind a watched section. Its reports land as posts. */
    loop_id: string | null;
    answer: DataAnswer | null;
    replies: DiscussionPost[];
  }

  export interface DiscussionReplyResult extends DiscussionThread {
    delivery: AgentDelivery;
  }

  export interface DiscussionStart {
    content: string;
    anchor_key: string;
    anchor_text: string;
    kind?: DiscussionKind;
    task_id?: string | null;
    loop_id?: string | null;
    send_to_agent?: boolean;
  }

  export interface DiscussionReply {
    content: string;
    /** A task the client just started for this thread. The thread keeps it. */
    task_id?: string | null;
    send_to_agent?: boolean;
  }

  export interface SpaceHome {
    docs: DocSummary[];
    watches: WatchSummary[];
  }

  export interface DocWrite {
    channel: string;
    title?: string;
    template?: DocTemplate;
  }

  export interface DocUpdate {
    title?: string;
    status?: DocStatus;
  }

  export interface CollabSave {
    client_id: string;
    steps: unknown[];
    version: number;
    content: ProseMirrorDoc;
    text_content?: string;
    title?: string;
    cursor_head?: number;
  }

  export interface CollabConflict {
    code: "conflict" | "stale";
    steps?: unknown[];
    client_ids?: string[];
    version: number;
  }

  export interface CaretPing {
    client_id: string;
    version: number;
    cursor: { anchor: number; head: number };
  }
}

const docsPath = (projectId: string): string =>
  `/api/projects/${projectId}/docs/`;
const docPath = (projectId: string, docId: string): string =>
  `/api/projects/${projectId}/docs/${docId}/`;
const docActionPath = (
  projectId: string,
  docId: string,
  action: string,
): string => `/api/projects/${projectId}/docs/${docId}/${action}/`;

/** Non-2xx docs response, with the parsed body so callers can branch on a conflict. */
export class DocsApiError extends Error {
  constructor(
    readonly method: Method,
    readonly path: string,
    readonly status: number,
    readonly body: unknown,
  ) {
    super(`Docs request failed: ${method.toUpperCase()} ${path} (${status})`);
    this.name = "DocsApiError";
  }
}

async function readBody(response: Response): Promise<unknown> {
  try {
    return await response.clone().json();
  } catch {
    return null;
  }
}

async function docsRequest<T>(
  client: ApiClient,
  method: Method,
  path: string,
  options?: { query?: Record<string, unknown>; body?: unknown },
): Promise<T> {
  const encodeSearchParams =
    client.fetcher.encodeSearchParams ?? client.defaultEncodeSearchParams;
  const parseResponseData =
    client.fetcher.parseResponseData ?? client.defaultParseResponseData;

  // The shared fetcher throws on any non-2xx, so a conflict arrives here as an
  // exception, not as a response. Re-shape it into a DocsApiError so callers can
  // branch on the status instead of parsing a message.
  let response: Response;
  try {
    response = await client.fetcher.fetch({
      method,
      path,
      url: new URL(client.baseUrl + path),
      urlSearchParams: encodeSearchParams(options?.query),
      parameters: { body: options?.body },
    });
  } catch (error) {
    if (error instanceof ApiRequestError) {
      throw new DocsApiError(method, path, error.status, error.body);
    }
    throw error;
  }

  if (!response.ok) {
    throw new DocsApiError(
      method,
      path,
      response.status,
      await readBody(response),
    );
  }
  if (response.status === 204) return undefined as T;
  return (await parseResponseData(response)) as T;
}

export async function listDocs(
  client: ApiClient,
  projectId: string,
  channelId: string,
): Promise<DocSchemas.DocSummary[]> {
  return docsRequest(client, "get", docsPath(projectId), {
    query: { channel: channelId },
  });
}

export async function retrieveDoc(
  client: ApiClient,
  projectId: string,
  docId: string,
): Promise<DocSchemas.Doc> {
  return docsRequest(client, "get", docPath(projectId, docId));
}

export async function createDoc(
  client: ApiClient,
  projectId: string,
  body: DocSchemas.DocWrite,
): Promise<DocSchemas.Doc> {
  return docsRequest(client, "post", docsPath(projectId), { body });
}

export async function updateDoc(
  client: ApiClient,
  projectId: string,
  docId: string,
  body: DocSchemas.DocUpdate,
): Promise<DocSchemas.Doc> {
  return docsRequest(client, "patch", docPath(projectId, docId), { body });
}

export async function deleteDoc(
  client: ApiClient,
  projectId: string,
  docId: string,
): Promise<void> {
  await docsRequest(client, "delete", docPath(projectId, docId));
}

export async function reorderDocs(
  client: ApiClient,
  projectId: string,
  channelId: string,
  docIds: string[],
): Promise<void> {
  await docsRequest(client, "post", `${docsPath(projectId)}reorder/`, {
    body: { channel: channelId, doc_ids: docIds },
  });
}

/** The space's context notes as a doc, created on first use. */
export async function retrieveContextDoc(
  client: ApiClient,
  projectId: string,
  channelId: string,
): Promise<DocSchemas.Doc> {
  return docsRequest(client, "get", `${docsPath(projectId)}context/`, {
    query: { channel: channelId },
  });
}

export async function retrieveSpaceHome(
  client: ApiClient,
  projectId: string,
  channelId: string,
): Promise<DocSchemas.SpaceHome> {
  return docsRequest(client, "get", `${docsPath(projectId)}home/`, {
    query: { channel: channelId },
  });
}

/**
 * Append a batch of prosemirror-collab steps. A 409 (other steps landed first)
 * and a 410 (the client must reload) come back as `CollabConflict` rather than
 * throwing, because both are ordinary outcomes of two people typing.
 */
export async function saveDocSteps(
  client: ApiClient,
  projectId: string,
  docId: string,
  body: DocSchemas.CollabSave,
): Promise<
  | { status: "accepted"; doc: DocSchemas.Doc }
  | { status: "conflict" | "stale"; conflict: DocSchemas.CollabConflict }
> {
  try {
    const doc = await docsRequest<DocSchemas.Doc>(
      client,
      "post",
      docActionPath(projectId, docId, "collab/save"),
      { body },
    );
    return { status: "accepted", doc };
  } catch (error) {
    if (
      error instanceof DocsApiError &&
      (error.status === 409 || error.status === 410)
    ) {
      const conflict = error.body as DocSchemas.CollabConflict;
      return {
        status: conflict.code === "stale" ? "stale" : "conflict",
        conflict,
      };
    }
    throw error;
  }
}

export async function sendDocCaret(
  client: ApiClient,
  projectId: string,
  docId: string,
  body: DocSchemas.CaretPing,
): Promise<void> {
  await docsRequest(
    client,
    "post",
    docActionPath(projectId, docId, "collab/presence"),
    { body },
  );
}

/** The doc's live stream. Read `response.body` and feed it to an SSE parser. */
export async function openDocStream(
  client: ApiClient,
  projectId: string,
  docId: string,
  options: { lastEventId: string; signal: AbortSignal },
): Promise<Response> {
  const path = docActionPath(projectId, docId, "collab/stream");
  return client.fetcher.fetch({
    method: "get",
    path,
    url: new URL(client.baseUrl + path),
    parameters: {
      header: {
        Accept: "text/event-stream",
        "Last-Event-ID": options.lastEventId,
      },
    },
    overrides: { signal: options.signal },
  });
}

export async function listDiscussions(
  client: ApiClient,
  projectId: string,
  docId: string,
): Promise<DocSchemas.DiscussionThread[]> {
  return docsRequest(
    client,
    "get",
    docActionPath(projectId, docId, "discussions"),
  );
}

export async function startDiscussion(
  client: ApiClient,
  projectId: string,
  docId: string,
  body: DocSchemas.DiscussionStart,
): Promise<DocSchemas.DiscussionReplyResult> {
  return docsRequest(
    client,
    "post",
    docActionPath(projectId, docId, "discussions"),
    { body },
  );
}

export async function replyToDiscussion(
  client: ApiClient,
  projectId: string,
  docId: string,
  threadId: string,
  body: DocSchemas.DiscussionReply,
): Promise<DocSchemas.DiscussionReplyResult> {
  return docsRequest(
    client,
    "post",
    docActionPath(projectId, docId, `discussions/${threadId}/reply`),
    { body },
  );
}

export async function setDiscussionResolved(
  client: ApiClient,
  projectId: string,
  docId: string,
  threadId: string,
  resolved: boolean,
): Promise<DocSchemas.DiscussionThread> {
  return docsRequest(
    client,
    "post",
    docActionPath(projectId, docId, `discussions/${threadId}/resolve`),
    { body: { resolved } },
  );
}

/**
 * Saved insights matching a search, for the picker that inserts a chart into a
 * doc. This reads the ordinary insights endpoint, not a docs one: a doc stores
 * a reference to an insight, so it never needs its own copy of the list.
 */
export async function searchInsightsForDoc(
  client: ApiClient,
  projectId: string,
  search: string,
  limit = 20,
): Promise<
  Array<{ short_id: string; name: string; derived_name: string | null }>
> {
  const page = await docsRequest<{
    results: Array<{
      short_id: string;
      name: string;
      derived_name: string | null;
    }>;
  }>(client, "get", `/api/projects/${projectId}/insights/`, {
    query: { search, limit, basic: true },
  });
  return page.results ?? [];
}
