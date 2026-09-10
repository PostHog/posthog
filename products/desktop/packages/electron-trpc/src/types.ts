import type { Operation } from "@trpc/client";
import type { TRPCResponseMessage } from "@trpc/server/rpc";

export type ETRPCRequest =
  | { method: "request"; operation: Operation }
  | { method: "subscription.stop"; id: string | number }
  | { method: "operation.cancel"; id: string | number };

export interface RendererGlobalElectronTRPC {
  sendMessage: (args: ETRPCRequest) => void;
  onMessage: (callback: (args: TRPCResponseMessage) => void) => void;
}
