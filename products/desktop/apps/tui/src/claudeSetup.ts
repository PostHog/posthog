import { spawn } from "node:child_process";
import { accessSync, constants } from "node:fs";
import { delimiter, join } from "node:path";
import type { Writable } from "node:stream";
import { stripTerminalSequences } from "@earendil-works/pi-tui";

// Whether `claude` is on PATH, so `claude setup-token` can run from here.
export function claudeOnPath(
  path: string | undefined = process.env.PATH,
): boolean {
  return (path ?? "").split(delimiter).some((dir) => {
    try {
      accessSync(join(dir, "claude"), constants.X_OK);
      return true;
    } catch {
      return false;
    }
  });
}

const TOKEN = /sk-ant-oat01-[A-Za-z0-9_-]{29,}/;

// Runs `claude setup-token` on the user's terminal, mirroring what it prints, and returns the token it prints.
// The caller hands the terminal over first, so the command's browser prompt and any question reach the user.
export function runClaudeSetupToken(
  spawnCommand: typeof spawn = spawn,
  stdout: Writable = process.stdout,
): Promise<string> {
  return new Promise((resolve, reject) => {
    const child = spawnCommand("claude", ["setup-token"], {
      stdio: ["inherit", "pipe", "inherit"],
    });
    let printed = "";
    child.stdout?.on("data", (chunk: Buffer) => {
      stdout.write(chunk);
      printed += chunk.toString("utf8");
    });
    child.on("error", reject);
    child.on("close", (code) => {
      const token = TOKEN.exec(stripTerminalSequences(printed))?.[0];
      if (token) resolve(token);
      else
        reject(
          new Error(
            code === 0
              ? "claude setup-token printed no token"
              : `claude setup-token exited with ${code}`,
          ),
        );
    });
  });
}
