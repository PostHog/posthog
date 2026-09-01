(globalThis as unknown as { electronTRPC: unknown }).electronTRPC = {
  sendMessage: () => Promise.resolve(),
  onMessage: () => () => {},
};

export function ipcLink() {
  return () => {};
}
