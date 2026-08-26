import { describe, expect, it } from "vitest";
import { TurnController } from "./turn-controller";

describe("TurnController", () => {
  it("runs a turn through begin -> onStarted -> claim", async () => {
    const turns = new TurnController();
    const { completion } = turns.begin();
    expect(turns.isPending).toBe(true);
    expect(turns.isRunning).toBe(false);

    turns.onStarted("turn-1");
    expect(turns.isRunning).toBe(true);
    expect(turns.activeTurnId).toBe("turn-1");

    const pending = turns.claim();
    expect(pending).toBeDefined();
    expect(turns.isPending).toBe(false);
    expect(turns.activeTurnId).toBeUndefined();
    expect(turns.claim()).toBeUndefined();

    pending?.resolve({ stopReason: "end_turn" });
    await expect(completion).resolves.toEqual({ stopReason: "end_turn" });
  });

  it("finishPrompt for an older turn does not wipe a newer turn's pending state", async () => {
    const turns = new TurnController();

    // Turn A completes: finalize claims synchronously, then awaits before resolving.
    const a = turns.begin();
    turns.onStarted("turn-a");
    const claimedA = turns.claim();
    expect(claimedA).toBeDefined();

    // A new prompt lands inside finalize's await window and begins turn B.
    const b = turns.begin();
    turns.onStarted("turn-b");

    // Turn A's prompt() resolves and its finally runs; it must not clear turn B.
    claimedA?.resolve({ stopReason: "end_turn" });
    await expect(a.completion).resolves.toEqual({ stopReason: "end_turn" });
    turns.finishPrompt(a.turn);

    expect(turns.isRunning).toBe(true);
    const claimedB = turns.claim();
    expect(claimedB).toBeDefined();
    claimedB?.resolve({ stopReason: "end_turn" });
    await expect(b.completion).resolves.toEqual({ stopReason: "end_turn" });
  });

  it("finishPrompt with the current turn token clears the pending slot", () => {
    const turns = new TurnController();
    const { turn } = turns.begin();
    turns.finishPrompt(turn);
    expect(turns.isPending).toBe(false);
    expect(turns.claim()).toBeUndefined();
  });

  it("fail clears the turn id so a later interrupt skips the RPC", async () => {
    const turns = new TurnController();
    const { completion } = turns.begin();
    turns.onStarted("turn-1");

    turns.fail(new Error("codex app-server exited"));
    await expect(completion).rejects.toThrow("codex app-server exited");
    expect(turns.activeTurnId).toBeUndefined();
    expect(turns.markInterrupted()).toBeUndefined();
  });

  it("markInterrupted flags the live turn and shouldDropCompletion fires once", () => {
    const turns = new TurnController();
    turns.begin();
    turns.onStarted("turn-1");

    expect(turns.markInterrupted()).toBe("turn-1");
    expect(turns.shouldDropCompletion("turn-1")).toBe(true);
    expect(turns.shouldDropCompletion("turn-1")).toBe(false);
    expect(turns.shouldDropCompletion(undefined)).toBe(false);
  });

  it("close resolves the pending turn and resets all state", async () => {
    const turns = new TurnController();
    const { completion } = turns.begin();
    turns.onStarted("turn-1");
    turns.markInterrupted();

    turns.close("cancelled");
    await expect(completion).resolves.toEqual({ stopReason: "cancelled" });
    expect(turns.isPending).toBe(false);
    expect(turns.activeTurnId).toBeUndefined();
    expect(turns.shouldDropCompletion("turn-1")).toBe(false);
  });

  it("onSteered rotates the active turn id", () => {
    const turns = new TurnController();
    turns.begin();
    turns.onStarted("turn-1");
    turns.onSteered("turn-2");
    expect(turns.activeTurnId).toBe("turn-2");
    turns.onSteered(undefined);
    expect(turns.activeTurnId).toBe("turn-2");
  });
});
