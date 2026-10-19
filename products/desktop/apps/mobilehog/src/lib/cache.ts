import { createSyncStoragePersister } from "@tanstack/query-sync-storage-persister";
import { hydrate, type QueryClient } from "@tanstack/react-query";
import {
  type PersistedClient,
  persistQueryClientSubscribe,
} from "@tanstack/react-query-persist-client";
import * as Crypto from "expo-crypto";
import { File } from "expo-file-system";
import * as SecureStore from "expo-secure-store";
import { createMMKV, deleteMMKV, type MMKV } from "react-native-mmkv";
import type { Photo } from "@/lib/attachments";
import { type Session, useAuth } from "@/lib/auth";
import type { Block } from "@/lib/transcript";

export const CACHE_MAX_AGE = 7 * 24 * 60 * 60 * 1000;
const KEY_NAME = "mobilehog_cache_key";
const CACHED_QUERIES = new Set(["tasks", "reports", "activity", "models"]);

const stores = new Map<string, MMKV>();

// Cached tasks can hold code and secrets, so the store is encrypted with a device key.
function encryptionKey(): string {
  const saved = SecureStore.getItem(KEY_NAME);
  if (saved) return saved;
  const key = Array.from(Crypto.getRandomBytes(16), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
  SecureStore.setItem(KEY_NAME, key);
  return key;
}

function storeId(session: Session): string {
  const host = Array.from(session.host, (character) =>
    character.charCodeAt(0).toString(16),
  ).join("");
  return `cache-${host}-${session.userId}`;
}

export function accountStore(session: Session): MMKV {
  const id = storeId(session);
  let store = stores.get(id);
  if (!store) {
    store = createMMKV({
      id,
      encryptionKey: encryptionKey(),
      encryptionType: "AES-256",
    });
    stores.set(id, store);
  }
  return store;
}

export function clearAccountCache(session: Session): void {
  const id = storeId(session);
  stores.delete(id);
  accountDrafts.delete(id);
  deleteMMKV(id);
}

// Restores synchronously so saved lists render on the first frame.
export function persistQueryCache(
  client: QueryClient,
  session: Session,
): () => void {
  const store = accountStore(session);
  const key = `queries-${session.projectId}`;
  const raw = store.getString(key);
  if (raw) {
    try {
      const saved = JSON.parse(raw) as PersistedClient;
      if (Date.now() - saved.timestamp < CACHE_MAX_AGE) {
        hydrate(client, saved.clientState);
      }
    } catch {
      store.remove(key);
    }
  }
  const persister = createSyncStoragePersister({
    key,
    throttleTime: 1000,
    storage: {
      getItem: (name) => store.getString(name) ?? null,
      setItem: (name, value) => store.set(name, value),
      removeItem: (name) => {
        store.remove(name);
      },
    },
  });
  return persistQueryClientSubscribe({
    queryClient: client,
    persister,
    buster: "",
    dehydrateOptions: {
      shouldDehydrateQuery: (query) =>
        query.state.status === "success" &&
        CACHED_QUERIES.has(String(query.queryKey[0])) &&
        !query.queryKey.includes("search"),
    },
  });
}

const TRANSCRIPT_LIMIT = 50;
const DRAFT_LIMIT = 50;

// The new-chat composer has no task id yet.
export const NEW_CHAT_DRAFT = "new-chat";

interface SavedTranscript {
  savedAt: number;
  blocks: Block[];
}

export interface Draft {
  text: string;
  photos: Photo[];
}

function projectScope(kind: string): { store: MMKV; prefix: string } | null {
  const { session } = useAuth.getState();
  if (!session) return null;
  return {
    store: accountStore(session),
    prefix: `${kind}-${session.projectId}`,
  };
}

function readIndex(store: MMKV, prefix: string): string[] {
  try {
    const order = JSON.parse(store.getString(`${prefix}-index`) ?? "[]");
    return Array.isArray(order)
      ? order.filter((item): item is string => typeof item === "string")
      : [];
  } catch {
    return [];
  }
}

// Moves the id to the front and drops the oldest entries past the limit.
function touchIndex(
  store: MMKV,
  prefix: string,
  id: string,
  limit: number,
): void {
  const order = [id, ...readIndex(store, prefix).filter((item) => item !== id)];
  for (const stale of order.slice(limit)) {
    store.remove(`${prefix}-${stale}`);
  }
  store.set(`${prefix}-index`, JSON.stringify(order.slice(0, limit)));
}

export function loadTranscript(taskId: string): Block[] | null {
  const scope = projectScope("transcript");
  const raw = scope?.store.getString(`${scope.prefix}-${taskId}`);
  if (!raw) return null;
  try {
    const saved = JSON.parse(raw) as SavedTranscript;
    return Date.now() - saved.savedAt < CACHE_MAX_AGE ? saved.blocks : null;
  } catch {
    return null;
  }
}

export function saveTranscript(taskId: string, blocks: Block[]): void {
  const scope = projectScope("transcript");
  if (!scope || blocks.length === 0) return;
  const saved: SavedTranscript = { savedAt: Date.now(), blocks };
  scope.store.set(`${scope.prefix}-${taskId}`, JSON.stringify(saved));
  touchIndex(scope.store, scope.prefix, taskId, TRANSCRIPT_LIMIT);
}

interface AccountDrafts {
  // A placeholder chat gets its task id after its screen saved under the
  // temporary id, so writes to that id follow the move.
  moved: Map<string, string>;
  // Messages whose send has not settled, by storage id. A saved message with
  // no entry here is from a send the app did not finish.
  sending: Map<string, Draft>;
}

interface DraftScope {
  store: MMKV;
  prefix: string;
  key: string;
  id: string;
  drafts: AccountDrafts;
}

const accountDrafts = new Map<string, AccountDrafts>();

function draftScope(key: string): DraftScope | null {
  const { session } = useAuth.getState();
  if (!session) return null;
  const account = storeId(session);
  let drafts = accountDrafts.get(account);
  if (!drafts) {
    drafts = { moved: new Map(), sending: new Map() };
    accountDrafts.set(account, drafts);
  }
  const prefix = `draft-${session.projectId}`;
  const target = drafts.moved.get(`${prefix}-${key}`) ?? key;
  return {
    store: accountStore(session),
    prefix,
    key: target,
    id: `${prefix}-${target}`,
    drafts,
  };
}

function hasContent(draft: Draft): boolean {
  return draft.text.trim().length > 0 || draft.photos.length > 0;
}

// Picker copies live in the caches directory, which iOS can purge between
// launches, so photos whose file is gone are dropped.
function isUsablePhoto(value: unknown): value is Photo {
  const photo = value as Partial<Photo> | null;
  if (
    typeof photo?.id !== "string" ||
    typeof photo.uri !== "string" ||
    typeof photo.name !== "string" ||
    typeof photo.mimeType !== "string" ||
    typeof photo.size !== "number"
  ) {
    return false;
  }
  try {
    return new File(photo.uri).exists;
  } catch {
    return false;
  }
}

function parseDraft(value: unknown): Draft {
  const draft = (value ?? {}) as { text?: unknown; photos?: unknown };
  return {
    text: typeof draft.text === "string" ? draft.text : "",
    photos: Array.isArray(draft.photos)
      ? draft.photos.filter(isUsablePhoto)
      : [],
  };
}

function readDraft(
  store: MMKV,
  id: string,
): { draft: Draft; unsent: Draft | null } | null {
  const raw = store.getString(id);
  if (!raw) return null;
  try {
    const saved = JSON.parse(raw);
    return {
      draft: parseDraft(saved),
      unsent: saved?.unsent ? parseDraft(saved.unsent) : null,
    };
  } catch {
    return null;
  }
}

function removeDraft({ store, prefix, key, id }: DraftScope): void {
  if (!store.contains(id)) return;
  store.remove(id);
  store.set(
    `${prefix}-index`,
    JSON.stringify(readIndex(store, prefix).filter((item) => item !== key)),
  );
}

function writeDraft(scope: DraftScope, draft: Draft): void {
  const unsent = scope.drafts.sending.get(scope.id);
  if (!hasContent(draft) && !unsent) {
    removeDraft(scope);
    return;
  }
  scope.store.set(
    scope.id,
    JSON.stringify({ text: draft.text, photos: draft.photos, unsent }),
  );
  touchIndex(scope.store, scope.prefix, scope.key, DRAFT_LIMIT);
}

// What the composer gets back when a send fails: text and photos typed since
// then win over the unsent ones.
export function keepUnsent(typed: Draft, unsent: Draft): Draft {
  return {
    text: typed.text.trim() ? typed.text : unsent.text,
    photos: typed.photos.length ? typed.photos : unsent.photos,
  };
}

export function loadDraft(key: string): Draft | null {
  const scope = draftScope(key);
  if (!scope) return null;
  const saved = readDraft(scope.store, scope.id);
  if (!saved) return null;
  let { draft } = saved;
  if (saved.unsent && !scope.drafts.sending.has(scope.id)) {
    draft = keepUnsent(draft, saved.unsent);
    writeDraft(scope, draft);
  }
  return hasContent(draft) ? draft : null;
}

export function saveDraft(key: string, draft: Draft): void {
  const scope = draftScope(key);
  if (scope) writeDraft(scope, { text: draft.text, photos: draft.photos });
}

// Keeps the message in the saved draft until the send settles, so it survives
// the app closing mid-send. Call the result with whether the send went out.
export function beginSend(
  key: string,
  message: Draft,
): (sent: boolean) => void {
  const scope = draftScope(key);
  if (!scope) return () => {};
  scope.drafts.sending.set(scope.id, message);
  writeDraft(scope, { text: "", photos: [] });
  return (sent) => {
    if (scope.drafts.sending.get(scope.id) === message) {
      scope.drafts.sending.delete(scope.id);
    }
    const current = projectScope("draft");
    if (current?.store !== scope.store || current.prefix !== scope.prefix) {
      return;
    }
    const typed = readDraft(scope.store, scope.id)?.draft ?? {
      text: "",
      photos: [],
    };
    writeDraft(scope, sent ? typed : keepUnsent(typed, message));
  };
}

export function moveDraft(from: string, to: string): void {
  const source = draftScope(from);
  const target = draftScope(to);
  if (!source || !target) return;
  source.drafts.moved.set(source.id, target.key);
  const saved = readDraft(source.store, source.id);
  removeDraft(source);
  if (saved) writeDraft(target, saved.draft);
}
