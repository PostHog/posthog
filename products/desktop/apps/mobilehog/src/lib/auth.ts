import { fetch } from "expo/fetch";
import * as SecureStore from "expo-secure-store";
import { create } from "zustand";
import { POSTHOG_HOST } from "@/config";
import {
  CLOUD_HOSTS,
  type CloudRegion,
  refreshOAuth,
  type SignInOptions,
  signInWithOAuth,
} from "@/lib/oauth";

const SESSION_KEY = "mobilehog_session";

export type Region = "local" | CloudRegion;

export interface Session {
  region: Region;
  host: string;
  apiKey: string;
  // OAuth sessions only; a local dev key never expires.
  refreshToken?: string;
  expiresAt?: number;
  scopedTeams?: number[];
  projectId: number;
  projectName: string;
  userId: number;
  userName: string;
  email?: string;
}

interface AuthState {
  session: Session | null;
  hydrated: boolean;
  generation: number;
  hydrate: () => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  loginWithOAuth: (
    region: CloudRegion,
    options?: SignInOptions,
  ) => Promise<void>;
  // Swaps an expired OAuth access token; returns the new bearer.
  refresh: () => Promise<string>;
  selectProject: (
    projectId: number,
    projectName: string,
    identity: string,
  ) => Promise<void>;
  logout: () => Promise<void>;
}

async function readJson<T>(response: Response, what: string): Promise<T> {
  if (!response.ok) {
    const text = await response.text().catch(() => "");
    let detail = text;
    try {
      const parsed = JSON.parse(text);
      detail = parsed.detail ?? parsed.error ?? text;
    } catch {}
    throw new Error(`${what} failed (${response.status}): ${detail}`);
  }
  return (await response.json()) as T;
}

// Log in without touching the cookie jar (a stale session there would trip the
// CSRF check), pull the session id out of the response, and swap it for the
// seeded local dev personal API key so every later call is a plain bearer.
async function loginWithPassword(
  email: string,
  password: string,
): Promise<Session> {
  const loginResponse = await fetch(`${POSTHOG_HOST}/api/login/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
    credentials: "omit",
  });
  await readJson<{ success?: boolean }>(loginResponse, "Login");
  const sessionId = /sessionid=([^;,\s]+)/.exec(
    loginResponse.headers.get("set-cookie") ?? "",
  )?.[1];
  if (!sessionId) {
    throw new Error("Login succeeded but no session cookie came back.");
  }

  const keysResponse = await fetch(`${POSTHOG_HOST}/api/personal_api_keys/`, {
    headers: { Cookie: `sessionid=${sessionId}` },
    credentials: "omit",
  });
  const keys = await readJson<Array<{ local_dev_value?: string | null }>>(
    keysResponse,
    "Reading API keys",
  );
  const apiKey = keys.find((key) => key.local_dev_value)?.local_dev_value;
  if (!apiKey) {
    throw new Error(
      "No local dev API key found. Run `python manage.py setup_local_api_key` and set ALLOW_DEV_API_KEY_REVEAL=1, then restart the stack.",
    );
  }

  return describeSession({ region: "local", host: POSTHOG_HOST, apiKey });
}

async function describeSession(base: {
  region: Region;
  host: string;
  apiKey: string;
  refreshToken?: string;
  expiresAt?: number;
  scopedTeams?: number[];
  projectId?: number;
}): Promise<Session> {
  const meResponse = await fetch(`${base.host}/api/users/@me/`, {
    headers: { Authorization: `Bearer ${base.apiKey}` },
    credentials: "omit",
  });
  const me = await readJson<{
    id: number;
    first_name: string;
    email: string;
    team?: { id: number; name: string } | null;
  }>(meResponse, "Loading user");
  const projectId = base.projectId ?? me.team?.id;
  if (!projectId) {
    throw new Error("This user has no current project.");
  }
  let projectName = me.team?.id === projectId ? me.team.name : null;
  if (!projectName) {
    const projectResponse = await fetch(
      `${base.host}/api/projects/${projectId}/`,
      {
        headers: { Authorization: `Bearer ${base.apiKey}` },
        credentials: "omit",
      },
    );
    projectName =
      (await readJson<{ name?: string }>(projectResponse, "Loading project"))
        .name ?? `Project ${projectId}`;
  }
  return {
    ...base,
    projectId,
    projectName,
    userId: me.id,
    userName: me.first_name || me.email,
    email: me.email,
  };
}

let storageWrite: Promise<void> = Promise.resolve();
let loginPending = false;

function queueStorageWrite(write: () => Promise<void>): Promise<void> {
  const pending = storageWrite.then(write);
  storageWrite = pending.catch(() => {});
  return pending;
}

export function sessionIdentity(state = useAuth.getState()): string {
  const { session, generation } = state;
  return JSON.stringify([
    generation,
    session?.host,
    session?.projectId,
    session?.userId,
  ]);
}

export function accountStorageKey(prefix: string): string {
  const session = requireSession();
  const host = Array.from(session.host, (character) =>
    character.charCodeAt(0).toString(16),
  ).join("-");
  return `${prefix}_${host}_${session.projectId}_${session.userId}`;
}

export const useAuth = create<AuthState>((set, get) => {
  const commit = async (
    session: Session,
    generation: number,
  ): Promise<void> => {
    await queueStorageWrite(async () => {
      if (get().generation !== generation)
        throw new Error("Session changed. Sign in again.");
      await SecureStore.setItemAsync(SESSION_KEY, JSON.stringify(session));
      if (get().generation !== generation)
        throw new Error("Session changed. Sign in again.");
      set({ session, hydrated: true });
    });
  };

  const login = async (attempt: () => Promise<Session>): Promise<void> => {
    if (loginPending) return;
    loginPending = true;
    if (get().session || !get().hydrated) {
      set({ session: null, generation: get().generation + 1, hydrated: true });
    }
    const generation = get().generation;
    try {
      await commit(await attempt(), generation);
    } finally {
      loginPending = false;
    }
  };

  return {
    session: null,
    hydrated: false,
    generation: 0,

    hydrate: async () => {
      if (get().hydrated) return;
      const generation = get().generation;
      try {
        const raw = await SecureStore.getItemAsync(SESSION_KEY);
        if (get().generation !== generation || get().session) return;
        set({
          session: raw ? (JSON.parse(raw) as Session) : null,
          hydrated: true,
        });
      } catch {
        if (get().generation === generation) set({ hydrated: true });
      }
    },

    login: (email, password) => login(() => loginWithPassword(email, password)),

    loginWithOAuth: (region, options) =>
      login(async () => {
        const tokens = await signInWithOAuth(region, options);
        return describeSession({
          region,
          host: CLOUD_HOSTS[region],
          apiKey: tokens.access_token,
          refreshToken: tokens.refresh_token,
          expiresAt: Date.now() + tokens.expires_in * 1000,
          projectId: tokens.scoped_teams?.[0],
          scopedTeams: tokens.scoped_teams,
        });
      }),

    refresh: async () => {
      const { session: current } = get();
      if (!current?.refreshToken || current.region === "local") {
        throw new Error("Session cannot be refreshed");
      }
      const tokens = await refreshOAuth(current.region, current.refreshToken);
      await queueStorageWrite(async () => {
        const assertCurrent = (): Session => {
          const latest = get().session;
          if (
            !latest ||
            latest.host !== current.host ||
            latest.userId !== current.userId ||
            latest.apiKey !== current.apiKey ||
            latest.refreshToken !== current.refreshToken
          ) {
            throw new Error("Session changed. Sign in again.");
          }
          return latest;
        };
        const session: Session = {
          ...assertCurrent(),
          apiKey: tokens.access_token,
          refreshToken: tokens.refresh_token || current.refreshToken,
          expiresAt: Date.now() + tokens.expires_in * 1000,
          scopedTeams: tokens.scoped_teams ?? current.scopedTeams,
        };
        await SecureStore.setItemAsync(SESSION_KEY, JSON.stringify(session));
        assertCurrent();
        set({ session });
      });
      return tokens.access_token;
    },

    selectProject: (projectId, projectName, identity) =>
      queueStorageWrite(async () => {
        const assertCurrent = (): void => {
          if (sessionIdentity(get()) !== identity || !get().session) {
            throw new Error("Session changed. Open Settings again.");
          }
        };
        assertCurrent();
        const current = requireSession();
        if (current.projectId === projectId) return;
        if (
          current.scopedTeams?.length &&
          !current.scopedTeams.includes(projectId)
        ) {
          throw new Error("This project is not available for this sign-in.");
        }
        const session = { ...current, projectId, projectName };
        await SecureStore.setItemAsync(SESSION_KEY, JSON.stringify(session));
        assertCurrent();
        set({ session, generation: get().generation + 1 });
      }),

    logout: async () => {
      set({ session: null, generation: get().generation + 1, hydrated: true });
      await queueStorageWrite(() => SecureStore.deleteItemAsync(SESSION_KEY));
    },
  };
});

export function requireSession(): Session {
  const { session } = useAuth.getState();
  if (!session) {
    throw new Error("Not signed in");
  }
  return session;
}
