import type { z } from "zod";

// The single seam for the web host's browser persistence. Every per-device
// store routes its reads and writes through here so the
// getItem -> JSON.parse -> guard -> JSON.stringify -> setItem boilerplate lives
// in exactly one place instead of being hand-rolled in each store.
//
// localStorage is the web host's one persistence layer. IndexedDB is used in
// exactly one place (web-auth-adapters.ts) and is deliberately NOT routed
// through here: it holds the non-extractable AES-GCM cipher key, which
// localStorage physically cannot store without exposing its raw bytes as a
// string — the very property that keeps a stolen token dump undecryptable
// offline. That is a key vault, not app state, so it stays separate.
//
// Versioning: every store here is a discardable per-device cache that rebuilds
// from the server or re-derives, so "drop what no longer fits and rebuild" IS
// the migration strategy. The validated readers below (readValidated,
// createRecordStore) parse persisted data against a Zod schema on load and shed
// anything that fails — a shape change needs only a schema edit, never a
// hand-written localStorage migration.
//
// Two write tiers. The best-effort helpers (writeJson/removeKey) swallow storage
// failures because for a rebuildable cache a dropped write only costs persistence
// across reloads, never correctness. The *Strict variants propagate the failure
// and MUST be used where a silently-dropped write would be a correctness or
// security bug — the auth session/preferences, where a clear() that looked like
// it succeeded but didn't would leave a stale session recoverable on reload.

export function readJson<T>(key: string, fallback: () => T): T {
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback();
  } catch {
    // Absent, corrupt, or unparseable: fall back rather than throw. Callers
    // treat missing state as empty.
    return fallback();
  }
}

export function writeJson<T>(key: string, value: T): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Best-effort: a storage failure (quota, privacy mode) only costs
    // persistence across reloads, never correctness — the in-memory value is
    // still authoritative for this session. Use writeJsonStrict where a dropped
    // write must surface.
  }
}

export function removeKey(key: string): void {
  try {
    window.localStorage.removeItem(key);
  } catch {
    // Best-effort, same rationale as writeJson. Use removeKeyStrict where a
    // dropped removal must surface (e.g. clearing an auth session on logout).
  }
}

// Strict write/remove: let storage failures propagate so the caller can react
// instead of treating a dropped write as success. For auth state (see the two-
// tier note above), not the rebuildable caches.
export function writeJsonStrict<T>(key: string, value: T): void {
  window.localStorage.setItem(key, JSON.stringify(value));
}

export function removeKeyStrict(key: string): void {
  window.localStorage.removeItem(key);
}

// Schema-validated read of a single persisted object. Parses the JSON, checks it
// against `schema`, and returns the fallback on any failure (absent, corrupt, or
// a shape that no longer matches — see the versioning note above).
export function readValidated<S extends z.ZodType>(
  key: string,
  schema: S,
  fallback: () => z.infer<S>,
): z.infer<S> {
  let raw: string | null;
  try {
    raw = window.localStorage.getItem(key);
  } catch {
    return fallback();
  }
  if (!raw) return fallback();
  try {
    const result = schema.safeParse(JSON.parse(raw));
    return result.success ? result.data : fallback();
  } catch {
    // Invalid JSON.
    return fallback();
  }
}

export interface JsonStore<T> {
  get(): T;
  set(value: T): void;
  clear(): void;
}

// A cached live store for the per-device registries (workspaces, archive, task
// metadata), which are all `Record<string, Entry>`: load once at construction,
// keep the value in memory, write through on every set. Each entry is validated
// against `entrySchema` on load and invalid entries are dropped individually, so
// a shape change sheds only the stale rows instead of nuking the whole map.
export function createRecordStore<S extends z.ZodType>(
  key: string,
  entrySchema: S,
): JsonStore<Record<string, z.infer<S>>> {
  const load = (): Record<string, z.infer<S>> => {
    const rawRecord = readJson<unknown>(key, () => ({}));
    if (typeof rawRecord !== "object" || rawRecord === null) return {};
    const valid: Record<string, z.infer<S>> = {};
    for (const [id, value] of Object.entries(rawRecord)) {
      const result = entrySchema.safeParse(value);
      if (result.success) valid[id] = result.data;
    }
    return valid;
  };

  let cache = load();
  return {
    get: () => cache,
    set: (value) => {
      cache = value;
      writeJson(key, value);
    },
    clear: () => {
      cache = {};
      removeKey(key);
    },
  };
}

// StateStorage backend for @posthog/ui's zustand persist (web-storage.ts).
// Zustand already serializes, so this passes raw strings straight through. It
// also lets storage errors propagate: the renderer persistence layer awaits and
// logs failed writes, so swallowing here would report a dropped draft/setting/
// layout write as a success that vanishes on reload.
export const rawLocalStorage = {
  getItem: (name: string): string | null => window.localStorage.getItem(name),
  setItem: (name: string, value: string): void => {
    window.localStorage.setItem(name, value);
  },
  removeItem: (name: string): void => {
    window.localStorage.removeItem(name);
  },
};
