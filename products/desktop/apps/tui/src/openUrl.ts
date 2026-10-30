import { execFile } from "node:child_process";
import { resolve, sep } from "node:path";
import { IMAGES_DIR } from "./images";
import { isWebUrl } from "./links";

// Opens a link in the default browser; clicks inside the TUI are captured, so the terminal cannot.
export function openUrl(url: string): void {
  if (!isWebUrl(url)) return;
  const command = process.platform === "darwin" ? "open" : "xdg-open";
  execFile(command, [url], () => {});
}

// Opens a sent image the TUI saved, in the default viewer; any other path is refused, so a click can never launch a program.
export function openImage(path: string): void {
  if (!resolve(path).startsWith(`${IMAGES_DIR}${sep}`)) return;
  const command = process.platform === "darwin" ? "open" : "xdg-open";
  execFile(command, [path], () => {});
}
