import { promises as fsp } from "node:fs";
import { afterAll, beforeAll, describe, expect, it } from "vitest";
import {
  isClaudePlanFilePath,
  isPlanReady,
} from "../src/adapters/claude/plan/utils";
import { type Adapter, E2E } from "./config";
import {
  type Capture,
  cleanupRepo,
  openSession,
  setupRepo,
  waitFor,
} from "./driver";

/**
 * Live plan-mode e2e — claude only. The Claude Code CLI assigns a plan file and has
 * the model build the plan up in it, so the plan under review only exists on disk:
 * `ExitPlanMode` itself carries no plan. This drives that end to end and asserts the
 * adapter publishes the file's content and its path. Codex plans through its own
 * switch_mode flow with no plan file, so it has nothing to assert here.
 *
 * Assertions are the wire contract, never model prose: the published plan equals the
 * file on disk, the path travels with it, and the text is a plan document rather than
 * assistant chat. The Write-then-Edit ordering is covered deterministically in
 * `permission-handlers.test.ts`.
 */
const ADAPTERS: Adapter[] = ["claude"];

const PLAN_PROMPT =
  "Do exactly this and nothing else. Plan a one-line change to target.txt so the " +
  "second line reads FOO instead of line2. Do not read other files and do not " +
  "launch subagents. Write the plan to your assigned plan file, then edit that " +
  "file to add a '## Verification' section. Then call ExitPlanMode.";

interface PlanRawInput {
  plan?: unknown;
  planFilePath?: unknown;
}

/**
 * The plan reaches the client on whichever emitter wins the race — the streamed
 * `tool_call` or the `tool_call_update` the permission handler publishes — so take
 * the first update carrying one, the same way the real client merges them.
 */
function findPublishedPlan(capture: Capture): PlanRawInput | undefined {
  for (const event of [
    ...capture.updates("tool_call"),
    ...capture.updates("tool_call_update"),
  ]) {
    const rawInput = (event.data as { rawInput?: PlanRawInput } | undefined)
      ?.rawInput;
    if (typeof rawInput?.plan === "string" && rawInput.plan.length > 0) {
      return rawInput;
    }
  }
  return undefined;
}

for (const adapter of ADAPTERS) {
  const skip = E2E.skipReason(adapter);
  const title = `plan mode (${adapter})${skip ? ` — SKIPPED (${skip})` : ""}`;

  describe.skipIf(!!skip)(title, () => {
    let repo: string;
    let planFilePath: string | undefined;

    beforeAll(() => {
      E2E.configureEnv(adapter);
      repo = setupRepo();
    });

    afterAll(async () => {
      cleanupRepo(repo);
      // The CLI writes plan files under the real plans directory, so remove the
      // one this run produced instead of leaving it in the developer's home.
      if (planFilePath && isClaudePlanFilePath(planFilePath)) {
        await fsp.rm(planFilePath, { force: true });
      }
    });

    it("publishes the plan file's content and path for review", async () => {
      const s = await openSession({
        adapter,
        cwd: repo,
        meta: {
          systemPrompt: "You are a coding assistant in a tiny test repo.",
          model: E2E.model(adapter),
          permissionMode: "plan",
        },
      });

      try {
        const p = s.conn.prompt({
          sessionId: s.sessionId,
          prompt: [{ type: "text", text: PLAN_PROMPT }],
        });

        // Plan mode runs a multi-phase workflow before it exits, so this waits well
        // past a normal turn. Cancelling once the plan is out keeps the cost to the
        // planning phase: approving would switch mode and start implementing.
        const published = await waitFor(
          () => findPublishedPlan(s.capture),
          180_000,
        );
        await s.conn.cancel({ sessionId: s.sessionId });
        await p.catch(() => undefined);

        expect(published).toBeDefined();
        planFilePath = published?.planFilePath as string | undefined;
        const plan = published?.plan as string;

        // The path travels with the plan so a client can open the document.
        expect(typeof planFilePath).toBe("string");
        expect(isClaudePlanFilePath(planFilePath)).toBe(true);

        // The plan under review is the file, not a reconstruction of it. Read after
        // the cancel: the model is done touching the plan file by then.
        expect(plan).toBe(await fsp.readFile(planFilePath as string, "utf8"));

        // A plan document, not the assistant's chat text.
        expect(isPlanReady(plan)).toBe(true);
      } finally {
        await s.cleanup();
      }
    });
  });
}
