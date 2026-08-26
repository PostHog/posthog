import { afterAll, beforeAll, describe, expect, it } from "vitest";
import { type Adapter, E2E } from "./config";
import {
  type Capture,
  type ConfigOption,
  cleanupRepo,
  INIT_PARAMS,
  type NewSessionResponse,
  ORIGINAL_TARGET,
  openConnection,
  openSession,
  readTarget,
  setupRepo,
  waitFor,
} from "./driver";

/**
 * Live session-lifecycle e2e per adapter: drives a real session end to end against
 * the real gateway + binary on a cheap model. Assertions are structural lifecycle
 * invariants + the on-disk edit, never model prose. Opt-in: each arm self-skips
 * unless `POSTHOG_CODE_E2E_GATEWAY_PERSONAL_API_KEY` is set (codex also needs the native binary).
 */
const ADAPTERS: Adapter[] = ["claude", "codex"];

const EDIT_PROMPT =
  "Do exactly these steps and nothing else: 1) Read the file target.txt. " +
  "2) Edit it so the second line reads FOO instead of line2. " +
  "3) Run the shell command `cat target.txt`. " +
  "4) In one sentence confirm what you changed, then stop.";

for (const adapter of ADAPTERS) {
  const skip = E2E.skipReason(adapter);
  const title = `session lifecycle (${adapter})${skip ? ` — SKIPPED (${skip})` : ""}`;
  // Codex-only; skipped on the claude arm so the gap is visible.
  const itCodex = adapter === "codex" ? it : it.skip;
  // Read-only profile only tightens per-turn on macOS + non-cloud (elsewhere the
  // spawn is danger-full-access / no profile), so gate to where it actually applies.
  const itCodexSandbox =
    adapter === "codex" &&
    process.platform === "darwin" &&
    E2E.environment !== "cloud"
      ? it
      : it.skip;

  describe.skipIf(!!skip)(title, () => {
    let repo: string;
    const codexOptions = () =>
      adapter === "codex" ? E2E.codexOptions(repo) : undefined;
    const meta = (extra: Record<string, unknown> = {}) => ({
      systemPrompt: "You are a coding assistant in a tiny test repo.",
      model: E2E.model(adapter),
      permissionMode: "bypassPermissions",
      // Drives the cloud ext-notifications (_posthog/sdk_session + turn_complete).
      taskRunId: "e2e-run",
      ...extra,
    });

    let sessionId: string;
    let newSessionResponse: NewSessionResponse;
    let turn:
      | { stopReason?: string; capture: Capture; target: string }
      | undefined;
    let goldenError: unknown;

    beforeAll(async () => {
      E2E.configureEnv(adapter);
      repo = setupRepo();
      const s = await openSession({
        adapter,
        cwd: repo,
        codexOptions: codexOptions(),
        meta: meta(),
      });
      sessionId = s.sessionId;
      newSessionResponse = s.newSession;
      try {
        const res = await s.conn.prompt({
          sessionId,
          prompt: [{ type: "text", text: EDIT_PROMPT }],
        });
        turn = {
          stopReason: res.stopReason,
          capture: s.capture,
          target: readTarget(repo),
        };
      } catch (err) {
        // Don't fail the whole describe on a flaky golden turn — record it so only
        // the test that consumes `turn` fails.
        goldenError = err;
      } finally {
        await s.cleanup();
      }
    }, 180_000);

    afterAll(() => {
      cleanupRepo(repo);
    });

    it("newSession exposes selectable config options (model / effort)", () => {
      const opts = newSessionResponse.configOptions ?? [];
      expect(opts.length).toBeGreaterThan(0);
      expect(opts.some((o) => (o.options?.length ?? 0) > 1)).toBe(true);
    });

    it("streams a working turn: assistant text, tool calls, usage, file edit", () => {
      if (goldenError) throw goldenError;
      if (!turn) throw new Error("golden turn did not produce a result");
      expect(turn.stopReason).toBe("end_turn");
      expect(
        turn.capture.updates("agent_message_chunk").length,
      ).toBeGreaterThan(0);
      expect(turn.capture.updates("tool_call").length).toBeGreaterThan(0);
      const anyToolCompleted = [
        ...turn.capture.updates("tool_call"),
        ...turn.capture.updates("tool_call_update"),
      ].some((e) => e.data?.status === "completed");
      expect(anyToolCompleted).toBe(true);

      const hasUsage =
        turn.capture.updates("usage_update").length > 0 ||
        turn.capture.extMethods().includes("_posthog/usage_update");
      expect(hasUsage).toBe(true);

      expect(turn.capture.extMethods()).toContain("_posthog/sdk_session");

      expect(turn.target).not.toBe(ORIGINAL_TARGET);
      expect(turn.target).toContain("FOO");

      // codex additionally emits turn_complete; claude signals completion via the prompt response.
      if (adapter === "codex") {
        // Reasoning parity is unit-covered (mapping.test.ts); a live assertion
        // would be flaky on the cheap model.
        expect(turn.capture.extMethods()).toContain("_posthog/turn_complete");
        const tc = turn.capture.events.find(
          (e) =>
            e.kind === "extNotification" &&
            e.method === "_posthog/turn_complete",
        );
        const usage = (tc?.data as { usage?: Record<string, number> })?.usage;
        expect(usage).toBeTruthy();
        expect(usage?.totalTokens ?? 0).toBeGreaterThan(0);
        expect(usage?.totalTokens).toBe(
          (usage?.inputTokens ?? 0) +
            (usage?.outputTokens ?? 0) +
            (usage?.cachedReadTokens ?? 0) +
            (usage?.cachedWriteTokens ?? 0),
        );
      }
    });

    it("switches a config option via setSessionConfigOption", async () => {
      const s = await openSession({
        adapter,
        cwd: repo,
        codexOptions: codexOptions(),
        meta: meta(),
      });
      try {
        const opt = (s.newSession.configOptions ?? []).find(
          (o) => (o.options?.length ?? 0) > 1,
        );
        expect(
          opt,
          "expected a config option with multiple values",
        ).toBeTruthy();
        const alt =
          opt?.options?.find((v) => v.value !== opt.currentValue) ??
          opt?.options?.[0];
        const res = await s.conn.setSessionConfigOption({
          sessionId: s.sessionId,
          configId: opt?.id,
          value: alt?.value,
        });
        expect(res).toBeTruthy();
        if (adapter === "codex") {
          // codex re-emits config_option_update as the side effect of a switch.
          expect(
            s.capture.updates("config_option_update").length,
          ).toBeGreaterThan(0);
        } else {
          // claude returns updated configOptions — assert the switch actually took,
          // not merely that an ack array was produced (unconditionally true).
          const updated = ((res?.configOptions ?? []) as ConfigOption[]).find(
            (o) => o.id === opt?.id,
          );
          expect(updated?.currentValue).toBe(alt?.value);
        }
      } finally {
        await s.cleanup();
      }
    }, 90_000);

    // Cloud host switches mode only via setSessionConfigOption(configId:"mode"), so exercise both arms.
    it("emits current_mode_update when the mode is switched via setSessionConfigOption", async () => {
      const s = await openSession({
        adapter,
        cwd: repo,
        codexOptions: codexOptions(),
        meta: meta(),
      });
      try {
        // codex synthesizes modes; claude exposes a "mode" configOption — pick an alternate value.
        let value = "read-only";
        if (adapter === "claude") {
          const modeOpt = (s.newSession.configOptions ?? []).find(
            (o) => o.id === "mode",
          );
          value =
            (modeOpt?.options?.find((v) => v.value !== modeOpt.currentValue)
              ?.value as string) ?? "plan";
        }
        await s.conn.setSessionConfigOption({
          sessionId: s.sessionId,
          configId: "mode",
          value,
        });
        expect(s.capture.updates("current_mode_update").length).toBeGreaterThan(
          0,
        );
      } finally {
        await s.cleanup();
      }
    }, 60_000);

    // Proves the mode picker isn't cosmetic: read-only maps to an OS-level
    // :read-only profile that blocks the write even though the host auto-approves.
    // macOS-only (see itCodexSandbox).
    itCodexSandbox(
      "read-only mode actually blocks a file edit (sandbox restricts, not just approval)",
      async () => {
        const s = await openSession({
          adapter,
          cwd: repo,
          codexOptions: codexOptions(),
          meta: meta(),
        });
        try {
          await s.conn.setSessionConfigOption({
            sessionId: s.sessionId,
            configId: "mode",
            value: "read-only",
          });
          const before = readTarget(repo);
          const res = await s.conn.prompt({
            sessionId: s.sessionId,
            prompt: [
              {
                type: "text",
                text:
                  "Use your file-editing tool to change target.txt so its second " +
                  "line reads SENTINEL_RO_EDIT. You MUST attempt the edit with your " +
                  "tool even if it appears restricted. Then stop.",
              },
            ],
          });
          expect(res.stopReason).toBeTruthy();
          // >=1 tool call, so a pure prose no-op can't masquerade as enforcement.
          expect(s.capture.updates("tool_call").length).toBeGreaterThan(0);
          // File unchanged: the read-only sandbox blocked the write despite host auto-approval.
          expect(readTarget(repo)).toBe(before);
          expect(readTarget(repo)).not.toContain("SENTINEL_RO_EDIT");
        } finally {
          await s.cleanup();
        }
      },
      180_000,
    );

    // Proves Plan is a real mode: codex only offers request_user_input in its plan
    // collaboration mode. Also covers the revert — the collaboration mode is sticky,
    // so switching back to auto must push default explicitly.
    itCodex(
      "plan mode engages codex's plan collaboration, and reverts when switched back to auto",
      async () => {
        const s = await openSession({
          adapter,
          cwd: repo,
          codexOptions: codexOptions(),
          meta: meta(),
        });
        const askToUseTool =
          "Before doing anything else, you MUST call the request_user_input tool " +
          "to ask the user a single question: whether to proceed with approach A " +
          "or approach B. Ask exactly that one question via the tool, then stop.";
        const questionCount = () =>
          s.capture
            .approvals()
            .filter((e) => e.data?.codeToolKind === "question").length;
        try {
          await s.conn.setSessionConfigOption({
            sessionId: s.sessionId,
            configId: "mode",
            value: "plan",
          });
          await s.conn.prompt({
            sessionId: s.sessionId,
            prompt: [{ type: "text", text: askToUseTool }],
          });
          const afterPlan = questionCount();
          expect(afterPlan).toBeGreaterThan(0);

          // Switch back to auto: request_user_input is gone, so the same prompt yields no new question.
          await s.conn.setSessionConfigOption({
            sessionId: s.sessionId,
            configId: "mode",
            value: "auto",
          });
          await s.conn.prompt({
            sessionId: s.sessionId,
            prompt: [{ type: "text", text: askToUseTool }],
          });
          expect(questionCount()).toBe(afterPlan);
        } finally {
          await s.cleanup();
        }
      },
      240_000,
    );

    it("handles the host's refresh_session extMethod per adapter", async () => {
      const s = await openSession({
        adapter,
        cwd: repo,
        codexOptions: codexOptions(),
        meta: meta(),
      });
      try {
        const call = s.conn.extMethod("_posthog/refresh_session", {
          mcpServers: [],
        });
        if (adapter === "claude") {
          // claude implements refresh_session; haiku is on the MCP-injection exclude
          // list, so it rejects on the model gate (not method-not-found), proving the
          // call reaches the handler.
          await expect(call).rejects.toThrow(/MCP injection/i);
        } else {
          // codex doesn't implement extMethod — the call rejects cleanly (known adapter divergence).
          await expect(call).rejects.toThrow();
        }
      } finally {
        await s.cleanup();
      }
    }, 60_000);

    // Known gap: the approval {decision} round-trip and requestPermission policy
    // aren't exercised here (codex auto-approves under danger-full-access) —
    // unit-covered in codex-app-server-agent.test.ts / approvals.test.ts.

    it("incorporates a prompt's _meta.prContext without error", async () => {
      const s = await openSession({
        adapter,
        cwd: repo,
        codexOptions: codexOptions(),
        meta: meta(),
      });
      try {
        // The host attaches prContext on PR-follow-up runs; both adapters prepend it.
        const res = await s.conn.prompt({
          sessionId: s.sessionId,
          prompt: [
            {
              type: "text",
              text: "Acknowledge the linked pull request in one short sentence, then stop.",
            },
          ],
          _meta: {
            prContext:
              "Context: PR #4242 'Fix the thing' is open and under review.",
          },
        });
        expect(res.stopReason).toBe("end_turn");
        expect(s.capture.updates("agent_message_chunk").length).toBeGreaterThan(
          0,
        );
      } finally {
        await s.cleanup();
      }
    }, 120_000);

    itCodex(
      "folds a mid-turn prompt into the running turn via steering",
      async () => {
        const s = await openSession({
          adapter,
          cwd: repo,
          codexOptions: codexOptions(),
          meta: meta(),
        });
        try {
          const p1 = s.conn.prompt({
            sessionId: s.sessionId,
            prompt: [
              {
                type: "text",
                text: "Count up from 1, one number per line, and keep going.",
              },
            ],
          });
          await waitFor(
            () =>
              s.capture.updates("agent_message_chunk").length > 0
                ? true
                : undefined,
            20_000,
          );
          const p2 = s.conn.prompt({
            sessionId: s.sessionId,
            prompt: [{ type: "text", text: "Now stop and say DONE." }],
          });
          const [r1] = await Promise.all([p1, p2]);
          expect(r1.stopReason).toBe("end_turn");
          expect(
            s.capture.updates("user_message_chunk").length,
          ).toBeGreaterThanOrEqual(2);
          // The steer proof: folded into a SINGLE turn (one turn_complete). Two would
          // mean the steer didn't take and p2 ran as its own turn.
          const turnCompletes = s.capture.events.filter(
            (e) =>
              e.kind === "extNotification" &&
              e.method === "_posthog/turn_complete",
          ).length;
          expect(
            turnCompletes,
            "expected the steered prompt to fold into one running turn (1 " +
              "turn_complete); 2 means the steer didn't take",
          ).toBe(1);
        } finally {
          await s.cleanup();
        }
      },
      120_000,
    );

    itCodex(
      "lists the session and forks it",
      async () => {
        const b = openConnection({
          adapter,
          cwd: repo,
          codexOptions: codexOptions(),
        });
        try {
          await b.conn.initialize(INIT_PARAMS);
          const listed = await b.conn.listSessions({ cwd: repo });
          const ids = (listed.sessions ?? []).map((x) => x.sessionId);
          expect(ids).toContain(sessionId);
          const forked = await b.conn.unstable_forkSession({
            sessionId,
            cwd: repo,
            mcpServers: [],
            _meta: { model: E2E.model(adapter) },
          });
          expect(forked.sessionId).toBeTruthy();
          expect(forked.sessionId).not.toBe(sessionId);
        } finally {
          await b.cleanup();
        }
      },
      60_000,
    );

    // Known gap: the permission DENY path isn't exercised (neither arm reliably
    // surfaces a deny-able approval to a cheap model) — unit-covered in
    // approvals.test.ts / codex-app-server-agent.test.ts.

    it("interrupts an in-flight turn", async () => {
      const s = await openSession({
        adapter,
        cwd: repo,
        codexOptions: codexOptions(),
        meta: meta(),
      });
      try {
        const p = s.conn.prompt({
          sessionId: s.sessionId,
          prompt: [
            {
              type: "text",
              text: "Count up from 1, one number per line, and never stop until told to.",
            },
          ],
        });
        // Cancel as soon as the turn is in flight (unbounded work, so no race).
        await waitFor(
          () =>
            s.capture.updates("agent_message_chunk").length > 0 ||
            s.capture.updates("tool_call").length > 0
              ? true
              : undefined,
          20_000,
        );
        await s.conn.cancel({ sessionId: s.sessionId });
        const res = await p;
        expect(res.stopReason).toBe("cancelled");

        // After a cancel the session must be usable again — a bounded follow-up must complete.
        const followUp = await s.conn.prompt({
          sessionId: s.sessionId,
          prompt: [{ type: "text", text: "Stop. Reply with just: OK" }],
        });
        expect(followUp.stopReason).toBe("end_turn");
      } finally {
        await s.cleanup();
      }
    }, 120_000);

    it("resumeSession reconnects and returns config options", async () => {
      const b = openConnection({
        adapter,
        cwd: repo,
        codexOptions: codexOptions(),
      });
      try {
        await b.conn.initialize(INIT_PARAMS);
        const resumed = await b.conn.resumeSession({
          sessionId,
          cwd: repo,
          mcpServers: [],
          _meta: { model: E2E.model(adapter) },
        });
        expect(resumed).toBeTruthy();
        expect(Array.isArray(resumed.configOptions)).toBe(true);
      } finally {
        await b.cleanup();
      }
    }, 60_000);

    it("reattach (loadSession) restores the session and replays the transcript", async () => {
      const b = openConnection({
        adapter,
        cwd: repo,
        codexOptions: codexOptions(),
      });
      try {
        await b.conn.initialize(INIT_PARAMS);
        const loaded = await b.conn.loadSession({
          sessionId,
          cwd: repo,
          mcpServers: [],
          _meta: { model: E2E.model(adapter) },
        });
        expect(loaded).toBeTruthy();
        // loadSession runs no turn, so any update here is replayed history. The
        // shape differs by adapter: codex replays message chunks, claude tool calls.
        const replayed = await waitFor(() => {
          const n =
            adapter === "codex"
              ? b.capture.updates("user_message_chunk").length +
                b.capture.updates("agent_message_chunk").length
              : b.capture.updates("tool_call").length +
                b.capture.updates("tool_call_update").length;
          return n > 0 ? n : undefined;
        }, 8000);
        expect(replayed ?? 0).toBeGreaterThan(0);
      } finally {
        await b.cleanup();
      }
    }, 60_000);
  });
}
