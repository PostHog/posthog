import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { AuthPrompt } from "@earendil-works/pi-ai";
import { getAgentDir, ModelRuntime } from "@earendil-works/pi-coding-agent";

// pi's own ChatGPT provider; the harness reads its login from pi's credential file.
export const CHATGPT_PROVIDER = "openai-codex";
export const CHATGPT_MODEL = `${CHATGPT_PROVIDER}/gpt-5.5`;

const authPath = (): string => join(getAgentDir(), "auth.json");

const PROFILE_CLAIM = "https://api.openai.com/profile";
const AUTH_CLAIM = "https://api.openai.com/auth";

type Claims = Record<
  string,
  { email?: string; chatgpt_plan_type?: string } | undefined
>;

const claimsOf = (access: string): Claims => {
  try {
    return JSON.parse(
      Buffer.from(access.split(".")[1] ?? "", "base64url").toString("utf8"),
    ) as Claims;
  } catch {
    return {};
  }
};

const emailOf = (access: string): string | null =>
  claimsOf(access)[PROFILE_CLAIM]?.email ?? null;

const accessOf = (path: string): string | undefined => {
  const saved = JSON.parse(readFileSync(path, "utf8")) as Record<
    string,
    { access?: string } | undefined
  >;
  return saved[CHATGPT_PROVIDER]?.access;
};

// The plan the ChatGPT login is on ("ChatGPT Plus"), from its access token; "ChatGPT plan" when the token hides it.
export function chatgptPlan(path: string = authPath()): string {
  try {
    const access = accessOf(path);
    const type = access
      ? claimsOf(access)[AUTH_CLAIM]?.chatgpt_plan_type
      : undefined;
    return type
      ? `ChatGPT ${type.charAt(0).toUpperCase()}${type.slice(1)}`
      : "ChatGPT plan";
  } catch {
    return "ChatGPT plan";
  }
}

// The login's email from its access token, "ChatGPT" when the token hides it, null when nobody is logged in.
export function chatgptAccount(path: string = authPath()): string | null {
  try {
    const access = accessOf(path);
    return access ? (emailOf(access) ?? "ChatGPT") : null;
  } catch {
    return null;
  }
}

export interface ChatgptLoginUi {
  openUrl(url: string): void;
  // Asks the user a question; rejects when `signal` aborts, which happens once the browser answered it.
  prompt(message: string, signal?: AbortSignal): Promise<string>;
}

// Runs pi's browser login for ChatGPT and saves the result where the harness reads it.
export async function chatgptLogin(
  ui: ChatgptLoginUi,
  signal: AbortSignal,
): Promise<string | null> {
  const runtime = await ModelRuntime.create({ authPath: authPath() });
  await runtime.login(CHATGPT_PROVIDER, "oauth", {
    signal,
    prompt: (prompt: AuthPrompt) =>
      prompt.type === "select"
        ? Promise.resolve(prompt.options[0].id)
        : ui.prompt(prompt.message, prompt.signal),
    notify: (event) => {
      if (event.type === "auth_url") ui.openUrl(event.url);
    },
  });
  return chatgptAccount();
}

export async function chatgptLogout(): Promise<void> {
  const runtime = await ModelRuntime.create({ authPath: authPath() });
  await runtime.logout(CHATGPT_PROVIDER);
}
