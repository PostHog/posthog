import { once } from "node:events";
import { mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Logger } from "../../utils/logger";
import { spawnFxAcpProcess } from "./spawn";

const logger = new Logger({ debug: false, prefix: "[test]" });

let dir: string | null = null;

function isAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

afterEach(async () => {
  if (dir) await rm(dir, { recursive: true, force: true });
  dir = null;
});

describe("spawnFxAcpProcess", () => {
  it.skipIf(process.platform === "win32")(
    "kills a tool process that outlives fx",
    async () => {
      dir = await mkdtemp(join(tmpdir(), "fx-spawn-"));
      const pidFile = join(dir, "tool.pid");
      const binaryPath = join(dir, "fx");
      await writeFile(
        binaryPath,
        `#!/bin/sh\nsleep 60 &\necho $! > "${pidFile}"\n`,
        { mode: 0o755 },
      );
      const fx = await spawnFxAcpProcess({
        binaryPath,
        cwd: dir,
        model: "gpt-6-sol",
        gatewayKey: "local-key",
        logger,
      });
      await once(fx.process, "exit");
      const toolPid = Number((await readFile(pidFile, "utf8")).trim());
      expect(isAlive(toolPid)).toBe(true);

      await fx.kill();

      await vi.waitFor(() => expect(isAlive(toolPid)).toBe(false));
    },
  );
});
