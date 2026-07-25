import type { StopReason } from "@agentclientprotocol/sdk";
import { describe, expect, it, vi } from "vitest";
import { createOutputSink } from "./output";
import {
  exitCodeFor,
  type RunOptions,
  runTurn,
  type TurnConnection,
} from "./run";

// The exit code is the CLI's machine-facing contract: a script branching on $?
// has no other signal, so every stop reason's mapping is pinned here.
describe("exitCodeFor", () => {
  it.each([
    { stopReason: "end_turn", expected: 0 },
    { stopReason: "refusal", expected: 2 },
    { stopReason: "max_tokens", expected: 3 },
    { stopReason: "max_turn_requests", expected: 3 },
    // No signal arrived, so a cancelled turn is a failure the caller should see.
    { stopReason: "cancelled", expected: 1 },
  ] satisfies { stopReason: StopReason; expected: number }[])(
    "maps $stopReason to $expected",
    ({ stopReason, expected }) => {
      expect(exitCodeFor(stopReason)).toBe(expected);
    },
  );

  it("maps an unrecognized stop reason to 1", () => {
    expect(exitCodeFor("something_new" as StopReason)).toBe(1);
  });

  describe("when a signal interrupted the turn", () => {
    it.each([
      { label: "SIGINT", interruptedBy: 130 },
      { label: "SIGTERM", interruptedBy: 143 },
    ])(
      "reports $interruptedBy for $label whatever the adapter settled on",
      ({ interruptedBy }) => {
        // Including end_turn: the adapter can finish the turn cleanly in the
        // window between the signal and the cancel taking effect.
        for (const stopReason of [
          "cancelled",
          "end_turn",
          "refusal",
        ] satisfies StopReason[]) {
          expect(exitCodeFor(stopReason, interruptedBy)).toBe(interruptedBy);
        }
      },
    );
  });
});

function makeOptions(overrides: Partial<RunOptions> = {}): RunOptions {
  return {
    prompt: "do the thing",
    cwd: "/repo",
    permissionMode: "auto",
    output: "json",
    debug: false,
    ...overrides,
  };
}

function makeSink() {
  const chunks: string[] = [];
  const sink = createOutputSink("json", {
    write(s: string) {
      chunks.push(s);
      return true;
    },
  });
  return {
    sink,
    document: (): unknown =>
      chunks.length ? JSON.parse(chunks.join("")) : undefined,
  };
}

/** A connection whose prompt() stays pending until the test resolves it. */
function makeConnection(
  overrides: Partial<TurnConnection> = {},
): TurnConnection & {
  cancels: number;
  settlePrompt: (stopReason: StopReason) => void;
} {
  let settle: (result: { stopReason: StopReason }) => void = () => {};
  const conn = {
    cancels: 0,
    initialize: vi.fn().mockResolvedValue(undefined),
    newSession: vi.fn().mockResolvedValue({ sessionId: "sess-1" }),
    prompt: vi.fn(
      () =>
        new Promise<{ stopReason: StopReason }>((resolve) => {
          settle = resolve;
        }),
    ),
    async cancel() {
      conn.cancels += 1;
    },
    settlePrompt: (stopReason: StopReason) => settle({ stopReason }),
    ...overrides,
  };
  return conn as TurnConnection & {
    cancels: number;
    settlePrompt: (stopReason: StopReason) => void;
  };
}

function makeHooks() {
  const exits: number[] = [];
  const hooks = {
    debugLog: vi.fn(),
    markTearingDown: vi.fn(),
    cleanup: vi.fn().mockResolvedValue(undefined),
    exit: (code: number) => {
      exits.push(code);
    },
  };
  return { exits, hooks };
}

describe("runTurn", () => {
  it("returns the mapped exit code and emits the document on a clean turn", async () => {
    const conn = makeConnection();
    const { sink, document } = makeSink();
    const { hooks } = makeHooks();

    const pending = runTurn(conn, makeOptions(), sink, hooks);
    await vi.waitFor(() => expect(conn.prompt).toHaveBeenCalled());
    conn.settlePrompt("end_turn");

    expect(await pending).toBe(0);
    expect(document()).toEqual({
      text: "",
      stopReason: "end_turn",
      usage: null,
      sessionId: "sess-1",
    });
    expect(hooks.cleanup).toHaveBeenCalledTimes(1);
    expect(hooks.markTearingDown).toHaveBeenCalled();
  });

  it("passes the session _meta the flags asked for", async () => {
    const conn = makeConnection();
    const { sink } = makeSink();
    const { hooks } = makeHooks();

    const pending = runTurn(
      conn,
      makeOptions({
        permissionMode: "bypassPermissions",
        model: "claude-sonnet-4-5",
        systemPrompt: "be terse",
      }),
      sink,
      hooks,
    );
    await vi.waitFor(() => expect(conn.prompt).toHaveBeenCalled());
    conn.settlePrompt("end_turn");
    await pending;

    expect(conn.newSession).toHaveBeenCalledWith(
      expect.objectContaining({
        cwd: "/repo",
        _meta: {
          permissionMode: "bypassPermissions",
          model: "claude-sonnet-4-5",
          systemPrompt: "be terse",
        },
      }),
    );
  });

  it("omits model and systemPrompt from _meta when unset", async () => {
    const conn = makeConnection();
    const { sink } = makeSink();
    const { hooks } = makeHooks();

    const pending = runTurn(conn, makeOptions(), sink, hooks);
    await vi.waitFor(() => expect(conn.prompt).toHaveBeenCalled());
    conn.settlePrompt("end_turn");
    await pending;

    expect(conn.newSession).toHaveBeenCalledWith(
      expect.objectContaining({ _meta: { permissionMode: "auto" } }),
    );
  });

  it("removes both signal handlers on the way out", async () => {
    const before = {
      sigint: process.listenerCount("SIGINT"),
      sigterm: process.listenerCount("SIGTERM"),
    };
    const conn = makeConnection();
    const { sink } = makeSink();
    const { hooks } = makeHooks();

    const pending = runTurn(conn, makeOptions(), sink, hooks);
    await vi.waitFor(() => expect(conn.prompt).toHaveBeenCalled());
    expect(process.listenerCount("SIGTERM")).toBe(before.sigterm + 1);
    conn.settlePrompt("end_turn");
    await pending;

    expect(process.listenerCount("SIGINT")).toBe(before.sigint);
    expect(process.listenerCount("SIGTERM")).toBe(before.sigterm);
  });

  describe.each([
    { signal: "SIGINT" as const, expected: 130 },
    { signal: "SIGTERM" as const, expected: 143 },
  ])("$signal during a turn", ({ signal, expected }) => {
    it(`cancels the session and returns ${expected}`, async () => {
      const conn = makeConnection();
      const { sink } = makeSink();
      const { hooks } = makeHooks();

      const pending = runTurn(conn, makeOptions(), sink, hooks);
      await vi.waitFor(() => expect(conn.prompt).toHaveBeenCalled());

      process.emit(signal);
      await vi.waitFor(() => expect(conn.cancels).toBeGreaterThan(0));
      // The adapter resolves a cancelled turn rather than rejecting it.
      conn.settlePrompt("cancelled");

      expect(await pending).toBe(expected);
      expect(hooks.cleanup).toHaveBeenCalledTimes(1);
    });

    it("reports the signal even when the turn completed anyway", async () => {
      const conn = makeConnection();
      const { sink } = makeSink();
      const { hooks } = makeHooks();

      const pending = runTurn(conn, makeOptions(), sink, hooks);
      await vi.waitFor(() => expect(conn.prompt).toHaveBeenCalled());

      process.emit(signal);
      await vi.waitFor(() => expect(conn.cancels).toBeGreaterThan(0));
      conn.settlePrompt("end_turn");

      expect(await pending).toBe(expected);
    });
  });

  // The adapter discards a cancel that arrives before the turn activates, so the
  // guard after newSession is the only thing that stops the turn opening at all.
  it("stops before opening a turn when a signal landed during session setup", async () => {
    let releaseSession: (v: { sessionId: string }) => void = () => {};
    const conn = makeConnection({
      newSession: vi.fn(
        () =>
          new Promise<{ sessionId: string }>((resolve) => {
            releaseSession = resolve;
          }),
      ),
    });
    const { sink } = makeSink();
    const { hooks, exits } = makeHooks();

    const pending = runTurn(conn, makeOptions(), sink, hooks);
    await vi.waitFor(() => expect(conn.newSession).toHaveBeenCalled());

    process.emit("SIGINT");
    // No sessionId yet, so the handler tears down and exits directly.
    await vi.waitFor(() => expect(exits).toEqual([130]));
    expect(hooks.markTearingDown).toHaveBeenCalled();

    releaseSession({ sessionId: "sess-1" });

    expect(await pending).toBe(130);
    expect(conn.prompt).not.toHaveBeenCalled();
  });
});
