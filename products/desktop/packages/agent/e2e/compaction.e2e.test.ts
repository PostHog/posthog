import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { type Adapter, E2E } from "./config";
import { cleanupRepo, openSession, setupRepo } from "./driver";

/**
 * Live compaction e2e — codex only. codex auto-compacts when the context crosses
 * `model_auto_compact_token_limit`; we spawn with a low limit and a big cheap input
 * blob so a later turn trips it, and the adapter must surface `_posthog/compact_boundary`.
 * Claude is excluded: its manual `/compact` hangs `prompt()` and forcing auto
 * compaction is too costly. Tuning: if it never compacts, raise the limit and FILLER together.
 */
const ADAPTERS: Adapter[] = ["codex"];

// A limit above codex's resident baseline, with FILLER > limit so the crossing is baseline-independent.
const AUTO_COMPACT_TOKEN_LIMIT = 16000;
// ~20k tokens (~45 chars ≈ 11 tokens × 1800) — larger than the limit above.
const FILLER = "The quick brown fox jumps over the lazy dog. ".repeat(1800);
const MAX_CODEX_TURNS = 3;

for (const adapter of ADAPTERS) {
  const skip = E2E.skipReason(adapter);
  const title = `compaction (${adapter})${skip ? ` — SKIPPED (${skip})` : ""}`;

  describe.skipIf(!!skip)(title, () => {
    let repo: string;

    beforeAll(() => {
      E2E.configureEnv(adapter);
      repo = setupRepo();
    });

    afterAll(() => {
      cleanupRepo(repo);
    });

    it("surfaces a compaction to the host via compact_boundary", async () => {
      const s = await openSession({
        adapter,
        cwd: repo,
        codexOptions: E2E.codexOptions(repo, {
          // The model-scoped key is the effective one; set both to be safe.
          model_auto_compact_token_limit: AUTO_COMPACT_TOKEN_LIMIT,
          auto_compact_token_limit: AUTO_COMPACT_TOKEN_LIMIT,
        }),
        meta: {
          systemPrompt: "You are a coding assistant in a tiny test repo.",
          model: E2E.model(adapter),
          permissionMode: "bypassPermissions",
          taskRunId: "e2e-compaction",
        },
      });
      try {
        const compacted = () =>
          s.capture.extMethods().includes("_posthog/compact_boundary");

        // Turn 1's big input blob fills the context past the limit; turn 2+
        // trips auto-compaction. Stop once the boundary is surfaced.
        for (let i = 0; i < MAX_CODEX_TURNS && !compacted(); i++) {
          const text =
            i === 0
              ? `Reference text — do not summarize, reply with only: OK.\n\n${FILLER}`
              : "Reply with only: DONE.";
          await s.conn.prompt({
            sessionId: s.sessionId,
            prompt: [{ type: "text", text }],
          });
        }

        expect(
          compacted(),
          `expected a _posthog/compact_boundary; saw methods: ${s.capture
            .extMethods()
            .join(", ")}`,
        ).toBe(true);
      } finally {
        await s.cleanup();
      }
    }, 300_000);
  });
}
