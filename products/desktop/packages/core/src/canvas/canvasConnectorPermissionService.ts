import { injectable } from "inversify";
import { createStore } from "zustand/vanilla";

export const CANVAS_CONNECTOR_PERMISSION_SERVICE = Symbol.for(
  "posthog.canvas.connectorPermissionService",
);

export interface CanvasConnectorPermission {
  provider: string;
  tool: string;
  arguments?: Record<string, unknown>;
  reason: "canvas" | "tool";
}

interface PendingPermission extends CanvasConnectorPermission {
  owner: symbol;
  resolve: (allowed: boolean) => void;
}

@injectable()
export class CanvasConnectorPermissionService {
  readonly store = createStore<{ pending: PendingPermission[] }>(() => ({
    pending: [],
  }));

  request(
    owner: symbol,
    input: CanvasConnectorPermission,
    signal?: AbortSignal,
  ): Promise<boolean> {
    if (signal?.aborted) return Promise.resolve(false);
    return new Promise((resolve) => {
      const request: PendingPermission = {
        ...input,
        owner,
        resolve: (allowed) => {
          signal?.removeEventListener("abort", cancel);
          resolve(allowed);
        },
      };
      const cancel = () => this.respond(request, false);
      signal?.addEventListener("abort", cancel, { once: true });
      this.store.setState(({ pending }) => ({
        pending: [...pending, request],
      }));
    });
  }

  respond(request: PendingPermission, allowed: boolean): void {
    if (!this.store.getState().pending.includes(request)) return;
    this.store.setState(({ pending }) => ({
      pending: pending.filter((entry) => entry !== request),
    }));
    request.resolve(allowed);
  }

  cancel(owner: symbol): void {
    for (const request of this.store.getState().pending) {
      if (request.owner === owner) this.respond(request, false);
    }
  }
}
