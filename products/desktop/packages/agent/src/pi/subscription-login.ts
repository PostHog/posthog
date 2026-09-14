import { join } from "node:path";
import type { AuthInteraction, AuthPrompt } from "@earendil-works/pi-ai";
import type { ModelRuntime } from "@earendil-works/pi-coding-agent";
import type {
  PiSubscriptionLoginState,
  PiSubscriptionProvider,
} from "@posthog/shared";

export type { PiSubscriptionLoginState, PiSubscriptionProvider };

const LOGIN_TIMEOUT_MS = 10 * 60_000;

let sharedRuntime: Promise<ModelRuntime> | undefined;

/**
 * A lightweight, network-free `ModelRuntime`, shared across calls, pointed
 * at pi's own `~/.pi/agent/auth.json`. That is the same file a real Pi
 * session (spawned by `rpc-host.ts`) reads by default, so a login here is
 * immediately usable by the next session, and vice versa for anyone who has
 * also logged in via the standalone `pi` CLI.
 */
async function getSharedModelRuntime(): Promise<ModelRuntime> {
  sharedRuntime ??= (async () => {
    const pi = await import("@earendil-works/pi-coding-agent");
    return pi.ModelRuntime.create({
      authPath: join(pi.getAgentDir(), "auth.json"),
      allowModelNetwork: false,
      refreshOnCreate: false,
    });
  })();
  return sharedRuntime;
}

/**
 * Local, no-network read of the stored credential. Mirrors the Claude Code
 * adapter's `hasClaudeLogin`: reports what is on disk, not whether the
 * token is still valid — a live request refreshes it on demand.
 */
export async function piSubscriptionLoginState(
  provider: PiSubscriptionProvider,
): Promise<PiSubscriptionLoginState> {
  try {
    const runtime = await getSharedModelRuntime();
    const stored = await runtime.listCredentials();
    const credential = stored.find((entry) => entry.providerId === provider);
    if (!credential) {
      return "logged-out";
    }
    return credential.type === "oauth" ? "logged-in" : "logged-out";
  } catch {
    return "unknown";
  }
}

export async function signOutPiSubscription(
  provider: PiSubscriptionProvider,
): Promise<void> {
  const runtime = await getSharedModelRuntime();
  await runtime.logout(provider);
}

function pickLoginMethod(
  prompt: Extract<AuthPrompt, { type: "select" }>,
): string {
  const browserOption = prompt.options.find(
    (option) => /browser/i.test(option.id) || /browser/i.test(option.label),
  );
  return (browserOption ?? prompt.options[0])?.id ?? "";
}

/**
 * Bridges pi-ai's login `AuthInteraction` to a single `authUrl` for the host
 * to open externally. Anthropic and OpenAI Codex's OAuth flows always
 * `notify({type: "auth_url"})` before waiting on their local callback
 * server, racing it against a `manual_code` prompt for pasting the code by
 * hand. We don't offer that fallback yet, so its prompt is left pending
 * (never resolving) rather than rejected — rejecting it early would cancel
 * the callback-server wait it's racing against and abort the real flow.
 */
function createLoginInteraction(
  signal: AbortSignal,
  onAuthUrl: (url: string) => void,
): AuthInteraction {
  return {
    signal,
    notify(event) {
      if (event.type === "auth_url") {
        onAuthUrl(event.url);
      }
    },
    prompt(prompt): Promise<string> {
      if (prompt.type === "select") {
        return Promise.resolve(pickLoginMethod(prompt));
      }
      return new Promise<string>((_, reject) => {
        const cancel = (): void => reject(new Error("Sign-in was cancelled"));
        if (signal.aborted) {
          cancel();
          return;
        }
        signal.addEventListener("abort", cancel, { once: true });
      });
    },
  };
}

export interface PiSubscriptionLoginSession {
  authUrl: string;
  completed: Promise<boolean>;
  cancel: () => void;
}

/**
 * Starts pi-ai's native OAuth login for `provider` and resolves with the
 * browser URL as soon as it's known, while `completed` keeps running in the
 * background until the callback server (or cancellation) settles it. On
 * success, the credential is persisted to the shared auth.json — no further
 * wiring needed for a subsequent Pi session to pick it up.
 */
export async function startPiSubscriptionLogin(
  provider: PiSubscriptionProvider,
): Promise<PiSubscriptionLoginSession> {
  const runtime = await getSharedModelRuntime();
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), LOGIN_TIMEOUT_MS);

  let resolveAuthUrl: (url: string) => void = () => {};
  let rejectAuthUrl: (error: Error) => void = () => {};
  const authUrlPromise = new Promise<string>((resolve, reject) => {
    resolveAuthUrl = resolve;
    rejectAuthUrl = reject;
  });

  const interaction = createLoginInteraction(controller.signal, (url) =>
    resolveAuthUrl(url),
  );

  const completed = runtime
    .login(provider, "oauth", interaction)
    .then(() => true)
    .catch((error: unknown) => {
      rejectAuthUrl(error instanceof Error ? error : new Error(String(error)));
      return false;
    })
    .finally(() => clearTimeout(timeout));

  const authUrl = await authUrlPromise;

  return {
    authUrl,
    completed,
    cancel: () => controller.abort(),
  };
}
