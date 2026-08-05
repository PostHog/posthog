import type { PromptResponse, StopReason } from "@agentclientprotocol/sdk";

interface PendingTurn {
  resolve: (response: PromptResponse) => void;
  reject: (err: Error) => void;
}

/**
 * The turn state machine for one codex thread. A turn is async: `prompt()` starts it and
 * awaits a completion promise `turn/completed` (or interrupt/error) resolves. Owns the
 * in-flight `turnId`, the pending completion, and the ids of interrupted turns to drop.
 */
export class TurnController {
  private turnId?: string;
  private pending?: PendingTurn;
  private completion?: Promise<PromptResponse>;
  private generation = 0;
  private readonly cancelled = new Set<string>();

  begin(): { completion: Promise<PromptResponse>; turn: number } {
    const turn = ++this.generation;
    this.completion = new Promise<PromptResponse>((resolve, reject) => {
      this.pending = { resolve, reject };
    });
    return { completion: this.completion, turn };
  }

  /** The live turn id (steer precondition / interrupt target), if a turn started. */
  get activeTurnId(): string | undefined {
    return this.turnId;
  }

  get isPending(): boolean {
    return this.pending !== undefined;
  }

  /** A turn is running AND has a turnId — i.e. it can be steered. */
  get isRunning(): boolean {
    return this.pending !== undefined && this.turnId !== undefined;
  }

  /** Capture the turn id from turn/started (only while a turn is pending). */
  onStarted(id: string | undefined): void {
    if (this.pending && typeof id === "string") this.turnId = id;
  }

  onSteered(id: string | undefined): void {
    if (typeof id === "string") this.turnId = id;
  }

  /** Atomically claim the pending turn (clears the slot + turnId synchronously), or undefined if already claimed. */
  claim(): PendingTurn | undefined {
    const pending = this.pending;
    if (!pending) return undefined;
    this.pending = undefined;
    this.turnId = undefined;
    return pending;
  }

  /** Mark the live turn interrupted (so its late completion is dropped) and return its id, or undefined. */
  markInterrupted(): string | undefined {
    if (!this.turnId) return undefined;
    this.cancelled.add(this.turnId);
    return this.turnId;
  }

  /** True (once) if this completion is for an interrupted turn we should drop. */
  shouldDropCompletion(id: string | undefined): boolean {
    return id ? this.cancelled.delete(id) : false;
  }

  /**
   * Clear the pending slot after prompt() returns (covers a turn/start throw). Guarded by
   * the caller's turn token: finalizeTurn claims before it awaits, so a new prompt() can
   * begin() in that window; the older prompt's cleanup must not wipe the newer turn.
   */
  finishPrompt(turn: number): void {
    if (turn !== this.generation) return;
    this.pending = undefined;
    this.completion = undefined;
  }

  /** Reject the in-flight turn (e.g. the server exited before it completed). */
  fail(err: Error): void {
    this.turnId = undefined;
    this.pending?.reject(err);
    this.pending = undefined;
    this.completion = undefined;
  }

  /** Resolve and clear everything on session close. */
  close(reason: StopReason): void {
    this.turnId = undefined;
    this.pending?.resolve({ stopReason: reason });
    this.pending = undefined;
    this.completion = undefined;
    this.cancelled.clear();
  }
}
