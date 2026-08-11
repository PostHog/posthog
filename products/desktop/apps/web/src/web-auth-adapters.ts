import type {
  AuthOrgProjectPreferenceRecord,
  AuthPreferenceRecord,
  AuthSessionRecord,
  ConnectivityStatus,
  IAuthConnectivity,
  IAuthPreferenceStore,
  IAuthSessionStore,
  IAuthTokenCipher,
  PersistAuthSessionRecord,
} from "@posthog/core/auth/identifiers";
import type { IPowerManager } from "@posthog/platform/power-manager";
import type { CloudRegion } from "@posthog/shared";
import { readJson, removeKeyStrict, writeJsonStrict } from "./web-local-store";

// Web counterparts of the desktop auth adapters. Desktop persists the session
// in workspace-server SQLite behind a machine-bound node:crypto cipher and
// listens to OS power/network events; the browser keeps the same interfaces
// over localStorage and web platform events.

const SESSION_KEY = "posthog-code:auth-session";
const PREFERENCES_KEY = "posthog-code:auth-preferences";

export class WebAuthSessionStore implements IAuthSessionStore {
  getCurrent(): AuthSessionRecord | null {
    return readJson<AuthSessionRecord | null>(SESSION_KEY, () => null);
  }

  saveCurrent(input: PersistAuthSessionRecord): void {
    writeJsonStrict(SESSION_KEY, input);
  }

  clearCurrent(): void {
    // Strict: a swallowed failure here would report logout as complete while the
    // session stays in localStorage, recoverable on reload. Let it propagate.
    removeKeyStrict(SESSION_KEY);
  }
}

interface StoredPreferences {
  accounts: Record<string, AuthPreferenceRecord>;
  orgProjects: Record<string, AuthOrgProjectPreferenceRecord>;
}

export class WebAuthPreferenceStore implements IAuthPreferenceStore {
  get(
    accountKey: string,
    cloudRegion: CloudRegion,
  ): AuthPreferenceRecord | null {
    return this.read().accounts[`${accountKey}:${cloudRegion}`] ?? null;
  }

  save(input: AuthPreferenceRecord): void {
    const preferences = this.read();
    preferences.accounts[`${input.accountKey}:${input.cloudRegion}`] = input;
    this.write(preferences);
  }

  getOrgProject(
    accountKey: string,
    cloudRegion: CloudRegion,
    orgId: string,
  ): AuthOrgProjectPreferenceRecord | null {
    return (
      this.read().orgProjects[`${accountKey}:${cloudRegion}:${orgId}`] ?? null
    );
  }

  saveOrgProject(input: AuthOrgProjectPreferenceRecord): void {
    const preferences = this.read();
    preferences.orgProjects[
      `${input.accountKey}:${input.cloudRegion}:${input.orgId}`
    ] = input;
    this.write(preferences);
  }

  private read(): StoredPreferences {
    return readJson<StoredPreferences>(PREFERENCES_KEY, () => ({
      accounts: {},
      orgProjects: {},
    }));
  }

  private write(preferences: StoredPreferences): void {
    writeJsonStrict(PREFERENCES_KEY, preferences);
  }
}

// The refresh token has to survive reloads, so it can't live only in memory;
// the browser's at-rest options (localStorage/IndexedDB) are both readable by
// any JS on the origin. So we encrypt the token with AES-GCM under a
// *non-extractable* Web Crypto key kept in IndexedDB: the key object round-trips
// through structured clone, but its raw bytes are never exposed to JS. An XSS
// payload can still ask the live key to decrypt while it runs in the page, yet
// it cannot exfiltrate the key to decrypt a stolen localStorage dump offline or
// later — the same bar the desktop host's machine-bound cipher sets. (httpOnly
// cookies would be strictly better but need server-side session support the
// cloud web host doesn't have.) Web Crypto is async, hence the async contract.
const KEY_DB_NAME = "posthog-code:auth";
const KEY_STORE_NAME = "keys";
const KEY_ID = "refresh-token-cipher";
const AES_IV_BYTES = 12;

function openKeyDb(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(KEY_DB_NAME, 1);
    request.onupgradeneeded = () => {
      request.result.createObjectStore(KEY_STORE_NAME);
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function idbGet(db: IDBDatabase, key: string): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const request = db
      .transaction(KEY_STORE_NAME, "readonly")
      .objectStore(KEY_STORE_NAME)
      .get(key);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function idbPut(db: IDBDatabase, key: string, value: unknown): Promise<void> {
  return new Promise((resolve, reject) => {
    const tx = db.transaction(KEY_STORE_NAME, "readwrite");
    tx.objectStore(KEY_STORE_NAME).put(value, key);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

let cipherKeyPromise: Promise<CryptoKey> | null = null;

// Load the origin's cipher key from IndexedDB, generating and persisting one on
// first use. Memoised so concurrent encrypt/decrypt calls share a single init;
// a failed init clears the cache so a later call can retry.
function getCipherKey(): Promise<CryptoKey> {
  if (!cipherKeyPromise) {
    cipherKeyPromise = (async () => {
      const db = await openKeyDb();
      try {
        const existing = await idbGet(db, KEY_ID);
        if (existing instanceof CryptoKey) return existing;
        const key = await crypto.subtle.generateKey(
          { name: "AES-GCM", length: 256 },
          // extractable: false — the raw key bytes never leave the key store.
          false,
          ["encrypt", "decrypt"],
        );
        await idbPut(db, KEY_ID, key);
        return key;
      } finally {
        db.close();
      }
    })().catch((error) => {
      cipherKeyPromise = null;
      throw error;
    });
  }
  return cipherKeyPromise;
}

function toBase64(bytes: Uint8Array): string {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function fromBase64(value: string): Uint8Array {
  const binary = atob(value);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

export const webAuthTokenCipher: IAuthTokenCipher = {
  async encrypt(plaintext) {
    const key = await getCipherKey();
    const iv = crypto.getRandomValues(new Uint8Array(AES_IV_BYTES));
    const ciphertext = await crypto.subtle.encrypt(
      { name: "AES-GCM", iv },
      key,
      new TextEncoder().encode(plaintext),
    );
    // Prepend the per-message IV so decrypt is self-contained.
    const packed = new Uint8Array(iv.length + ciphertext.byteLength);
    packed.set(iv, 0);
    packed.set(new Uint8Array(ciphertext), iv.length);
    return toBase64(packed);
  },

  async decrypt(encrypted) {
    try {
      const key = await getCipherKey();
      const packed = fromBase64(encrypted);
      // Copy into fresh ArrayBuffer-backed views so the types satisfy
      // BufferSource (subarray widens the buffer to ArrayBufferLike).
      const iv = new Uint8Array(packed.subarray(0, AES_IV_BYTES));
      const data = new Uint8Array(packed.subarray(AES_IV_BYTES));
      const plaintext = await crypto.subtle.decrypt(
        { name: "AES-GCM", iv },
        key,
        data,
      );
      return new TextDecoder().decode(plaintext);
    } catch {
      // Corrupt data, a rotated/absent key, or a legacy plaintext token from
      // before encryption existed: treat as unrecoverable so auth clears the
      // session and re-authenticates.
      return null;
    }
  },
};

export class WebAuthConnectivity implements IAuthConnectivity {
  getStatus(): ConnectivityStatus {
    return { isOnline: navigator.onLine };
  }

  onStatusChange(handler: (status: ConnectivityStatus) => void): () => void {
    const online = () => handler({ isOnline: true });
    const offline = () => handler({ isOnline: false });
    window.addEventListener("online", online);
    window.addEventListener("offline", offline);
    return () => {
      window.removeEventListener("online", online);
      window.removeEventListener("offline", offline);
    };
  }
}

export const webPowerManager: IPowerManager = {
  onResume(handler: () => void): () => void {
    // Closest web analog to an OS resume signal: the tab becoming visible
    // again also covers waking from sleep.
    const listener = () => {
      if (document.visibilityState === "visible") handler();
    };
    document.addEventListener("visibilitychange", listener);
    return () => document.removeEventListener("visibilitychange", listener);
  },

  preventSleep(_reason: string): () => void {
    // Screen Wake Lock is the only browser primitive here; the request can be
    // refused (hidden tab, unsupported browser), which callers must treat the
    // same as no lock at all.
    const wakeLock = (navigator as { wakeLock?: WakeLock }).wakeLock;
    let released = false;
    let sentinel: WakeLockSentinel | null = null;
    wakeLock
      ?.request("screen")
      .then((lock) => {
        if (released) return lock.release();
        sentinel = lock;
      })
      .catch(() => {});
    return () => {
      released = true;
      void sentinel?.release().catch(() => {});
    };
  },

  hasBuiltInBattery(): Promise<boolean> {
    return Promise.resolve(false);
  },
};
