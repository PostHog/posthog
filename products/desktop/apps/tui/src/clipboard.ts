import { spawn } from "node:child_process";

// The terminal's own clipboard escape; it works over SSH, where a local command cannot reach the user's machine.
export function osc52(text: string): string {
  return `\u001b]52;c;${Buffer.from(text, "utf8").toString("base64")}\u0007`;
}

export function clipboardCommand(
  platform: NodeJS.Platform,
  env: NodeJS.ProcessEnv,
): [string, string[]] | null {
  if (env.SSH_TTY || env.SSH_CONNECTION) return null;
  if (platform === "darwin") return ["pbcopy", []];
  if (platform === "linux" && env.WAYLAND_DISPLAY) return ["wl-copy", []];
  if (platform === "linux" && env.DISPLAY)
    return ["xclip", ["-selection", "clipboard"]];
  return null;
}

// Copies with the system's clipboard command, or through the terminal when there is none or it fails.
export function copyToClipboard(text: string): void {
  const viaTerminal = (): void => {
    process.stdout.write(osc52(text));
  };
  const command = clipboardCommand(process.platform, process.env);
  if (!command) {
    viaTerminal();
    return;
  }
  const child = spawn(command[0], command[1], {
    stdio: ["pipe", "ignore", "ignore"],
  });
  child.on("error", viaTerminal);
  child.on("exit", (code) => {
    if (code !== 0) viaTerminal();
  });
  child.stdin.end(text);
}
