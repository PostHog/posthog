import { execFile, spawn } from "node:child_process";
import type { ImageContent } from "@earendil-works/pi-ai";

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

// AppleScript prints the clipboard's PNG as «data PNGf<hex>».
export function imageFromAppleScript(output: string): ImageContent | null {
  const hex = /«data PNGf([0-9A-F]+)»/.exec(output)?.[1];
  if (!hex) return null;
  return {
    type: "image",
    data: Buffer.from(hex, "hex").toString("base64"),
    mimeType: "image/png",
  };
}

// macOS only. Over SSH this machine's clipboard is not the user's, so there is nothing to read.
export function readClipboardImage(): Promise<ImageContent | null> {
  const { platform, env } = process;
  if (platform !== "darwin" || env.SSH_TTY || env.SSH_CONNECTION)
    return Promise.resolve(null);
  return new Promise((resolve) =>
    execFile(
      "osascript",
      ["-e", "get the clipboard as «class PNGf»"],
      { maxBuffer: 256 * 1024 * 1024 },
      (error, stdout) => resolve(error ? null : imageFromAppleScript(stdout)),
    ),
  );
}
