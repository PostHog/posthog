import { observable } from "@trpc/server/observable";

(globalThis as unknown as { electronTRPC: unknown }).electronTRPC = {
  sendMessage: () => Promise.resolve(),
  onMessage: () => () => {},
};

// A terminating link that never emits. Queries stay pending, and subscriptions
// attach instead of throwing "No more links to execute", which crashed any
// story rendering a component that subscribes to the host (GitHubConnectPanel).
export function ipcLink() {
  return () => () => observable(() => () => {});
}
