import { readFileSync, rmSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import type {
  CodexAuthTokens,
  UserCodexIntegration,
} from "@posthog/api-client/posthog-client";
import { CHATGPT_PROVIDER } from "./chatgpt";

// A second ChatGPT login for cloud Codex runs, as Desktop does. OpenAI rotates refresh tokens and PostHog refreshes
// the chain once it has them, so the local login's tokens cannot be shared: this login goes to its own file, its
// tokens go to PostHog, and the file goes.
export const CLOUD_AUTH_PATH = join(
  homedir(),
  ".config",
  "posthog-tui",
  "codex-cloud-auth.json",
);

export async function connectCodexCloud({
  login,
  connect,
  path = CLOUD_AUTH_PATH,
}: {
  login: (authPath: string) => Promise<void>;
  connect: (tokens: CodexAuthTokens) => Promise<UserCodexIntegration>;
  path?: string;
}): Promise<UserCodexIntegration> {
  try {
    await login(path);
    const saved = JSON.parse(readFileSync(path, "utf8")) as Record<
      string,
      { access?: string; refresh?: string } | undefined
    >;
    const credential = saved[CHATGPT_PROVIDER];
    if (!credential?.access || !credential.refresh)
      throw new Error("The login left no ChatGPT tokens behind");
    return await connect({
      access_token: credential.access,
      refresh_token: credential.refresh,
    });
  } finally {
    rmSync(path, { force: true });
  }
}
