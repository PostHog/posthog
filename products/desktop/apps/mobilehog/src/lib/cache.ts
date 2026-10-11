import type { Task } from "@posthog/shared/domain-types";
import { createSyncStoragePersister } from "@tanstack/query-sync-storage-persister";
import { hydrate, type QueryClient } from "@tanstack/react-query";
import {
  type PersistedClient,
  persistQueryClientSubscribe,
} from "@tanstack/react-query-persist-client";
import * as Crypto from "expo-crypto";
import * as SecureStore from "expo-secure-store";
import { createMMKV, deleteMMKV, type MMKV } from "react-native-mmkv";
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
const OPENED_LIMIT = 50;

interface SavedTranscript {
  savedAt: number;
  blocks: Block[];
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

export function recordOpened(taskId: string): void {
  const scope = projectScope("opened");
  if (scope) touchIndex(scope.store, scope.prefix, taskId, OPENED_LIMIT);
}

// Task ids opened on this device, most recent first.
export function loadOpened(): string[] {
  const scope = projectScope("opened");
  return scope ? readIndex(scope.store, scope.prefix) : [];
}

// Opened ids whose task is gone (deleted or archived) are skipped, and recent
// tasks fill the rest so a fresh install still shows something.
export function lastOpened(
  opened: string[],
  recent: Task[],
  limit: number,
): Task[] {
  const byId = new Map(recent.map((task) => [task.id, task]));
  const picked = new Map<string, Task>();
  for (const task of [
    ...opened.flatMap((id) => byId.get(id) ?? []),
    ...recent,
  ]) {
    if (picked.size === limit) break;
    picked.set(task.id, task);
  }
  return [...picked.values()];
}
