import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { E2E } from "./config";
import { type OpenSession, openSession } from "./driver";

const MODEL = "claude-sonnet-5-5";
const skip = E2E.skipReason("claude");

describe.skipIf(!!skip)(
  `context window (claude)${skip ? ` — SKIPPED (${skip})` : ""}`,
  () => {
    let cwd: string;

    beforeAll(() => {
      E2E.configureEnv("claude");
      cwd = mkdtempSync(join(tmpdir(), "e2e-context-window-"));
    });

    afterAll(() => {
      rmSync(cwd, { recursive: true, force: true });
    });

    async function lastSizeAfterTurn(s: OpenSession): Promise<unknown> {
      await s.conn.prompt({
        sessionId: s.sessionId,
        prompt: [{ type: "text", text: "Reply with only: OK." }],
      });
      return s.capture.updates("usage_update").at(-1)?.data?.size;
    }

    it("reports the window the CLI runs at, before and after a live switch", async () => {
      const s = await openSession({
        adapter: "claude",
        cwd,
        meta: {
          model: MODEL,
          contextWindow: "200k",
          permissionMode: "bypassPermissions",
          taskRunId: "e2e-context-window",
        },
      });
      try {
        expect(
          s.newSession.configOptions?.find((o) => o.id === "context_window")
            ?.currentValue,
        ).toBe("200k");
        expect(await lastSizeAfterTurn(s)).toBe(200_000);

        await s.conn.setSessionConfigOption({
          sessionId: s.sessionId,
          configId: "context_window",
          value: "1m",
        });
        expect(await lastSizeAfterTurn(s)).toBe(1_000_000);
      } finally {
        await s.cleanup();
      }
    }, 300_000);
  },
);
