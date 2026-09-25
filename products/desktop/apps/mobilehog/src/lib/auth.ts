import { fetch } from "expo/fetch";
import * as SecureStore from "expo-secure-store";
import { create } from "zustand";
import { POSTHOG_HOST } from "@/config";

const SESSION_KEY = "mobilehog_session";

export interface Session {
  apiKey: string;
  projectId: number;
  projectName: string;
  userId: number;
  userName: string;
}

interface AuthState {
  session: Session | null;
  hydrated: boolean;
  hydrate: () => Promise<void>;
  login: (email: string, password: string) => Promise<void>;
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

// Session-cookie login, then swap the cookie for the seeded local dev personal
// API key so every later call is a plain bearer request like v1 makes.
async function loginWithPassword(
  email: string,
  password: string,
): Promise<Session> {
  const loginResponse = await fetch(`${POSTHOG_HOST}/api/login/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  await readJson<{ success?: boolean }>(loginResponse, "Login");

  const keysResponse = await fetch(`${POSTHOG_HOST}/api/personal_api_keys/`);
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

  const meResponse = await fetch(`${POSTHOG_HOST}/api/users/@me/`, {
    headers: { Authorization: `Bearer ${apiKey}` },
  });
  const me = await readJson<{
    id: number;
    first_name: string;
    email: string;
    team?: { id: number; name: string } | null;
  }>(meResponse, "Loading user");
  if (!me.team) {
    throw new Error("This user has no current project.");
  }

  return {
    apiKey,
    projectId: me.team.id,
    projectName: me.team.name,
    userId: me.id,
    userName: me.first_name || me.email,
  };
}

export const useAuth = create<AuthState>((set) => ({
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
    await SecureStore.setItemAsync(SESSION_KEY, JSON.stringify(session));
    set({ session });
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
