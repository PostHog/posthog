import type { ShellClient } from "@posthog/ui/features/terminal/shellClient";

// There is no PTY/terminal in a browser. useSessionCallbacks resolves
// SHELL_CLIENT unconditionally when a chat view mounts (for the local
// bash-command path), but cloud tasks never invoke it (onBashCommand is wired
// only for local sessions). This stub exists so the eager useService call
// resolves; its methods reject/no-op since no shell can exist on web.
const notSupported = () =>
  Promise.reject(new Error("Terminal is not available on the web"));

export const webShellClient: ShellClient = {
  write: () => Promise.resolve(),
  check: () => Promise.resolve(false),
  destroy: () => Promise.resolve(),
  create: notSupported,
  createCommand: notSupported,
  resize: () => Promise.resolve(),
  getProcess: () => Promise.resolve(null),
  execute: () => notSupported() as Promise<never>,
  openExternal: ({ url }) => {
    window.open(url, "_blank", "noopener,noreferrer");
    return Promise.resolve();
  },
  onData: () => ({ unsubscribe: () => {} }),
  onExit: () => ({ unsubscribe: () => {} }),
};
