import { randomBytes } from "node:crypto";
import { readFileSync } from "node:fs";
import { PostHog } from "posthog-node";
import pkg from "../package.json" with { type: "json" };

// The desktop app's project, where its own events already go; the TUI is told apart by `app`.
const HOST = "https://internal-c.posthog.com";
const ANONYMOUS = "anonymous-tui";
// The desktop app's key is baked into its build; the TUI reads the same `.env` when the shell has not set one.
const DESKTOP_ENV = new URL("../../../../.env", import.meta.url);

export interface AnalyticsClient {
  capture(message: {
    distinctId: string;
    event: string;
    properties?: Record<string, unknown>;
  }): void;
  identify(message: { distinctId: string }): void;
  captureException(
    error: unknown,
    distinctId?: string,
    properties?: Record<string, unknown>,
  ): void;
  shutdown(): Promise<void>;
}

let client: AnalyticsClient | null = null;
let distinctId = ANONYMOUS;
const sessionId = uuidv7();

function uuidv7(): string {
  const bytes = randomBytes(16);
  const now = Date.now();
  for (let index = 0; index < 6; index++)
    bytes[index] = Math.floor(now / 2 ** (40 - index * 8)) & 0xff;
  bytes[6] = (bytes[6] & 0x0f) | 0x70;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = bytes.toString("hex");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function apiKey(): string | undefined {
  if (process.env.VITE_POSTHOG_API_KEY) return process.env.VITE_POSTHOG_API_KEY;
  // Tests must never reach the real project.
  if (process.env.VITEST) return undefined;
  try {
    return readFileSync(DESKTOP_ENV, "utf8").match(
      /^VITE_POSTHOG_API_KEY=(\S+)/m,
    )?.[1];
  } catch {
    return undefined;
  }
}

// Properties every event and exception carries, so a failure's trail can be read back per session.
function common(): Record<string, unknown> {
  return {
    app: "tui",
    team: "posthog-code",
    app_version: pkg.version,
    terminal: process.env.TERM_PROGRAM ?? process.env.TERM ?? null,
    os_platform: process.platform,
    $session_id: sessionId,
    $process_person_profile: distinctId !== ANONYMOUS,
  };
}

// Starts sending to the desktop app's project; without a key the TUI stays silent.
export function startAnalytics(withClient?: AnalyticsClient): void {
  if (withClient) {
    client = withClient;
    return;
  }
  const key = apiKey();
  if (!key || client) return;
  client = new PostHog(key, {
    host: process.env.VITE_POSTHOG_API_HOST || HOST,
  });
}

export function identify(id: string): void {
  distinctId = id;
  client?.identify({ distinctId: id });
}

export function track(
  event: string,
  properties: Record<string, unknown> = {},
): void {
  client?.capture({
    distinctId,
    event: `tui ${event}`,
    properties: { ...common(), ...properties },
  });
}

export function captureException(
  error: unknown,
  properties: Record<string, unknown> = {},
): void {
  client?.captureException(error, distinctId, { ...common(), ...properties });
}

export async function stopAnalytics(): Promise<void> {
  const stopping = client;
  client = null;
  distinctId = ANONYMOUS;
  await stopping?.shutdown();
}
