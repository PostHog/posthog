import type { PiSubscriptionLoginSession } from "./subscription-login";
import {
  piSubscriptionLoginState,
  signOutPiSubscription,
  startPiSubscriptionLogin,
} from "./subscription-login";

interface HostRequest {
  id: string;
  type: "status" | "login" | "logout" | "cancel";
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
      const loginState = await piSubscriptionLoginState();
      reply(request.id, { loginState });
      return;
    }
    case "logout": {
      await signOutPiSubscription();
      reply(request.id, {});
      return;
    }
    case "cancel": {
      activeLogin?.cancel();
      reply(request.id, {});
      return;
    }
    case "login": {
      const session = await startPiSubscriptionLogin();
      activeLogin = session;
      reply(request.id, { authUrl: session.authUrl });
      const loggedIn = await session.completed;
      process.send?.({ type: "login_completed", loggedIn });
      return;
    }
  }
}

process.on("message", (message: unknown) => {
  const request = message as Partial<HostRequest>;
  if (typeof request.id !== "string" || !request.type) {
    return;
  }
  handleRequest(request as HostRequest).catch((error) =>
    fail(request.id as string, error),
  );
});
