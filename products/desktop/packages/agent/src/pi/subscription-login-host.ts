import type { PiSubscriptionLoginSession } from "./subscription-login";
import {
  type PiSubscriptionProvider,
  piSubscriptionLoginState,
  signOutPiSubscription,
  startPiSubscriptionLogin,
} from "./subscription-login";

/**
 * Forked, short-lived entry point for Pi's own OAuth login. Kept in a
 * separate process (spawned by `subscription-login-client.ts`, mirroring
 * `hasClaudeLogin`'s CLI spawn and `openCodexAccountClient`'s app-server
 * spawn) so the Electron main bundle never has to import pi-ai/pi-coding-agent
 * directly — their auth flow modules deliberately obfuscate their own import
 * specifiers to keep bundlers from inlining them, which breaks when a
 * bundler tries anyway.
 */
interface HostRequest {
  id: string;
  type: "status" | "login" | "logout" | "cancel";
  provider: PiSubscriptionProvider;
}

let activeLogin: PiSubscriptionLoginSession | undefined;

function reply(id: string, data: unknown): void {
  process.send?.({ id, type: "response", data });
}

function fail(id: string, error: unknown): void {
  process.send?.({
    id,
    type: "error",
    error: error instanceof Error ? error.message : String(error),
  });
}

async function handleRequest(request: HostRequest): Promise<void> {
  switch (request.type) {
    case "status": {
      const loginState = await piSubscriptionLoginState(request.provider);
      reply(request.id, { loginState });
      return;
    }
    case "logout": {
      await signOutPiSubscription(request.provider);
      reply(request.id, {});
      return;
    }
    case "cancel": {
      activeLogin?.cancel();
      reply(request.id, {});
      return;
    }
    case "login": {
      const session = await startPiSubscriptionLogin(request.provider);
      activeLogin = session;
      reply(request.id, { authUrl: session.authUrl });
      const loggedIn = await session.completed;
      process.send?.({
        type: "login_completed",
        provider: request.provider,
        loggedIn,
      });
      return;
    }
  }
}

process.on("message", (message: unknown) => {
  const request = message as Partial<HostRequest>;
  if (typeof request.id !== "string" || !request.type || !request.provider) {
    return;
  }
  handleRequest(request as HostRequest).catch((error) =>
    fail(request.id as string, error),
  );
});
