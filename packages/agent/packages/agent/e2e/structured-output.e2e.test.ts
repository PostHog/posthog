import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { type Adapter, E2E } from "./config";
import { cleanupRepo, openSession, setupRepo } from "./driver";

/**
 * Live structured-output e2e: both adapters constrain the final message to a JSON
 * schema (`_meta.jsonSchema`) and deliver the parsed object via `onStructuredOutput`
 * — the contract the signals pipeline relies on. Deterministic answer so a cheap
 * model passes reliably. Opt-in (same gating as the lifecycle suite).
 */
const ADAPTERS: Adapter[] = ["claude", "codex"];

const SCHEMA = {
  type: "object",
  properties: { capital: { type: "string" } },
  required: ["capital"],
  additionalProperties: false,
};

for (const adapter of ADAPTERS) {
  const skip = E2E.skipReason(adapter);
  const title = `structured output (${adapter})${skip ? ` — SKIPPED (${skip})` : ""}`;

  describe.skipIf(!!skip)(title, () => {
    let repo: string;

    beforeAll(() => {
      E2E.configureEnv(adapter);
      repo = setupRepo();
    });

    afterAll(() => {
      cleanupRepo(repo);
    });

    it("delivers schema-constrained structured output", async () => {
      let captured: Record<string, unknown> | undefined;
      // The cheapest models hang on the constrained decode; use a stronger one.
      const model = E2E.strongModel(adapter);
      const s = await openSession({
        adapter,
        cwd: repo,
        codexOptions:
          adapter === "codex"
            ? E2E.codexOptions(repo, undefined, model)
            : undefined,
        onStructuredOutput: async (o) => {
          captured = o;
        },
        meta: {
          systemPrompt: "You answer strictly with JSON matching the schema.",
          model,
          permissionMode: "bypassPermissions",
          jsonSchema: SCHEMA,
          // Prod always sets taskRunId — exercise structured output + the session ext-notification together.
          taskRunId: "e2e-structured",
        },
      });
      try {
        const res = await s.conn.prompt({
          sessionId: s.sessionId,
          prompt: [
            {
              type: "text",
              text: "What is the capital of France? Answer using the required JSON schema.",
            },
          ],
        });
        expect(res.stopReason).toBe("end_turn");
        expect(captured, "onStructuredOutput should fire").toBeTruthy();
        expect(typeof captured?.capital).toBe("string");
        expect((captured?.capital as string).toLowerCase()).toContain("paris");
        expect(s.capture.extMethods()).toContain("_posthog/sdk_session");
      } finally {
        await s.cleanup();
      }
    }, 120_000);
  });
}
