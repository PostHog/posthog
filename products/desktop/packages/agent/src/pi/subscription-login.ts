import { join } from "node:path";
import type { AuthInteraction, AuthPrompt } from "@earendil-works/pi-ai";
import type { ModelRuntime } from "@earendil-works/pi-coding-agent";
import {
  PI_SUBSCRIPTION_PROVIDER,
  type PiSubscriptionLoginState,
} from "@posthog/shared";

export type { PiSubscriptionLoginState };

const LOGIN_TIMEOUT_MS = 10 * 60_000;

let sharedRuntime: Promise<ModelRuntime> | undefined;

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

export async function piSubscriptionLoginState(): Promise<PiSubscriptionLoginState> {
  try {
    const runtime = await getSharedModelRuntime();
    const stored = await runtime.listCredentials();
    const credential = stored.find(
      (entry) => entry.providerId === PI_SUBSCRIPTION_PROVIDER,
    );
    if (!credential) {
      return "logged-out";
    }
    return credential.type === "oauth" ? "logged-in" : "logged-out";
  } catch {
    return "unknown";
  }
}

export async function signOutPiSubscription(): Promise<void> {
  const runtime = await getSharedModelRuntime();
  await runtime.logout(PI_SUBSCRIPTION_PROVIDER);
}

export interface PiSubscriptionModelInfo {
  id: string;
  name: string;
}

export async function piSubscriptionModels(): Promise<
  PiSubscriptionModelInfo[]
> {
  try {
    const runtime = await getSharedModelRuntime();
    const models = await runtime.getAvailable(PI_SUBSCRIPTION_PROVIDER);
    return models.map((model) => ({ id: model.id, name: model.name }));
  } catch {
    return [];
  }
}

function pickLoginMethod(
  prompt: Extract<AuthPrompt, { type: "select" }>,
): string {
  const browserOption = prompt.options.find(
    (option) => /browser/i.test(option.id) || /browser/i.test(option.label),
  );
  return (browserOption ?? prompt.options[0])?.id ?? "";
}

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

export async function startPiSubscriptionLogin(): Promise<PiSubscriptionLoginSession> {
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
    .login(PI_SUBSCRIPTION_PROVIDER, "oauth", interaction)
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
