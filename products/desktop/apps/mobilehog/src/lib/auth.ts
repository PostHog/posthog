import { fetch } from "expo/fetch";
import * as SecureStore from "expo-secure-store";
import { create } from "zustand";
import { POSTHOG_HOST } from "@/config";
import {
  CLOUD_HOSTS,
  type CloudRegion,
  refreshOAuth,
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
  projectId: number;
  projectName: string;
  userId: number;
  userName: string;
  email?: string;
}

interface AuthState {
  session: Session | null;
  hydrated: boolean;
  hydrate: () => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
  loginWithOAuth: (region: CloudRegion, signup?: boolean) => Promise<void>;
  // Swaps an expired OAuth access token; returns the new bearer.
  refresh: () => Promise<string>;
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

async function persist(session: Session): Promise<void> {
  await SecureStore.setItemAsync(SESSION_KEY, JSON.stringify(session));
}

export const useAuth = create<AuthState>((set, get) => ({
  session: null,
  hydrated: false,

  hydrate: async () => {
    try {
      const raw = await SecureStore.getItemAsync(SESSION_KEY);
      set({
        session: raw ? (JSON.parse(raw) as Session) : null,
        hydrated: true,
      });
    } catch {
      set({ session: null, hydrated: true });
    }
  },

  login: async (email, password) => {
    const session = await loginWithPassword(email, password);
    await persist(session);
    set({ session });
  },

  loginWithOAuth: async (region, signup) => {
    const tokens = await signInWithOAuth(region, signup);
    const session = await describeSession({
      region,
      host: CLOUD_HOSTS[region],
      apiKey: tokens.access_token,
      refreshToken: tokens.refresh_token,
      expiresAt: Date.now() + tokens.expires_in * 1000,
      projectId: tokens.scoped_teams?.[0],
    });
    await persist(session);
    set({ session });
  },

  refresh: async () => {
    const current = get().session;
    if (!current?.refreshToken || current.region === "local") {
      throw new Error("Session cannot be refreshed");
    }
    const tokens = await refreshOAuth(current.region, current.refreshToken);
    const session: Session = {
      ...current,
      apiKey: tokens.access_token,
      refreshToken: tokens.refresh_token || current.refreshToken,
      expiresAt: Date.now() + tokens.expires_in * 1000,
    };
    await persist(session);
    set({ session });
    return session.apiKey;
  },

  logout: async () => {
    await SecureStore.deleteItemAsync(SESSION_KEY);
    set({ session: null });
  },
}));

export function requireSession(): Session {
  const { session } = useAuth.getState();
  if (!session) {
    throw new Error("Not signed in");
  }
  return session;
}
