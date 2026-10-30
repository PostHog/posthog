import { execFile } from "node:child_process";

// Opens a link in the default browser; clicks inside the TUI are captured, so the terminal cannot.
export function openUrl(url: string): void {
  const command = process.platform === "darwin" ? "open" : "xdg-open";
  execFile(command, [url], () => {});
}
