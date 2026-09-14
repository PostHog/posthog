import type { PiSubscriptionLoginSession } from "./subscription-login";
import {
  type PiSubscriptionProvider,
  piSubscriptionLoginState,
  signOutPiSubscription,
  startPiSubscriptionLogin,
} from "./subscription-login";

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
