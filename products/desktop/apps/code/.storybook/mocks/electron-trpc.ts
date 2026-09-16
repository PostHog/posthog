import { observable } from "@trpc/server/observable";

(globalThis as unknown as { electronTRPC: unknown }).electronTRPC = {
  sendMessage: () => Promise.resolve(),
  onMessage: () => () => {},
};

// A link that never emits: queries, mutations, and subscriptions through the
// host client stay pending in stories instead of throwing for a missing link.
export function ipcLink() {
  return () => () => observable(() => () => {});
}
