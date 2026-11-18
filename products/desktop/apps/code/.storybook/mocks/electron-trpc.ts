import { observable } from "@trpc/server/observable";

(globalThis as unknown as { electronTRPC: unknown }).electronTRPC = {
  sendMessage: () => Promise.resolve(),
  onMessage: () => () => {},
};

export function ipcLink() {
  return () => () => observable(() => () => {});
}
