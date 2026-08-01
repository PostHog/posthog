import type { ISpeech } from "@posthog/platform/speech";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { SpeechSettingsProvider, UserNameProvider } from "./identifiers";
import { SpeechQueueService } from "./speech";

/** A fake ISpeech whose `speak` resolves only when the test releases it. */
class ControllableSpeech implements ISpeech {
  spoken: string[] = [];
  private resolvers: Array<() => void> = [];

  isSupported(): boolean {
    return true;
  }

  speak(text: string): Promise<void> {
    this.spoken.push(text);
    return new Promise<void>((resolve) => {
      this.resolvers.push(resolve);
    });
  }

  stop(): void {}

  /** Finish the oldest in-flight utterance. */
  finishOne(): void {
    const resolve = this.resolvers.shift();
    resolve?.();
  }

  get inFlight(): number {
    return this.resolvers.length;
  }
}

const noopLogger = {
  debug: () => {},
  info: () => {},
  warn: () => {},
  error: () => {},
  scope: () => noopLogger,
};

function make(settings: Partial<{ enabled: boolean; voiceId?: string }> = {}) {
  const speech = new ControllableSpeech();
  const settingsProvider: SpeechSettingsProvider = {
    get: () => ({ enabled: true, ...settings }),
  };
  const userName: UserNameProvider = { getFirstName: () => "Jon" };
  const service = new SpeechQueueService(
    speech,
    settingsProvider,
    userName,
    noopLogger as never,
  );
  return { speech, service };
}

// let the queued microtasks (drain loop) run
const tick = () => new Promise((r) => setTimeout(r, 0));

describe("SpeechQueueService", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("speaks one utterance at a time", async () => {
    const { speech, service } = make();
    service.enqueue({ text: "one", taskTitle: "a", taskId: "1" });
    service.enqueue({ text: "two", taskTitle: "b", taskId: "2" });
    await tick();

    expect(speech.inFlight).toBe(1);
    expect(speech.spoken).toEqual(["PostHog task 'a' — one"]);

    speech.finishOne();
    await tick();
    expect(speech.spoken).toEqual([
      "PostHog task 'a' — one",
      "PostHog task 'b' — two",
    ]);
  });

  it("stays silent when narration is disabled", async () => {
    const { speech, service } = make({ enabled: false });
    service.enqueue({ text: "one", taskTitle: "a", taskId: "1" });
    await tick();
    expect(speech.spoken).toEqual([]);
  });

  it("coalesces a newer line for the same queued task", async () => {
    const { speech, service } = make();
    // First starts playing immediately (in-flight, not in queue).
    service.enqueue({ text: "start", taskTitle: "t", taskId: "1" });
    await tick();
    // These two queue behind it; second replaces the first for task 2.
    service.enqueue({ text: "stale", taskTitle: "t2", taskId: "2" });
    service.enqueue({ text: "fresh", taskTitle: "t2", taskId: "2" });
    await tick();

    speech.finishOne(); // finish "start"
    await tick();
    speech.finishOne(); // finish the task-2 line
    await tick();

    expect(speech.spoken).toEqual([
      "PostHog task 't' — start",
      "PostHog task 't2' — fresh",
    ]);
    expect(speech.spoken).not.toContain("PostHog task 't2' — stale");
  });

  it("prioritizes needs-user lines ahead of routine narration", async () => {
    const { speech, service } = make();
    service.enqueue({ text: "playing", taskTitle: "t", taskId: "1" });
    await tick();
    service.enqueue({ text: "routine", taskTitle: "t2", taskId: "2" });
    service.enqueue({
      text: "urgent",
      taskTitle: "t3",
      taskId: "3",
      needsUser: true,
      addressByName: true,
    });
    await tick();

    speech.finishOne(); // finish "playing"
    await tick();
    expect(speech.spoken[1]).toBe("PostHog task 't3' — Hey Jon, urgent");
  });

  it("drops oldest routine lines when the queue is backed up but keeps priority", async () => {
    const { speech, service } = make();
    service.enqueue({ text: "playing", taskTitle: "t", taskId: "0" });
    await tick();
    // Queue five routine lines behind the in-flight one (cap is 3).
    for (let i = 1; i <= 5; i++) {
      service.enqueue({ text: `r${i}`, taskTitle: `t${i}`, taskId: String(i) });
    }
    service.enqueue({
      text: "urgent",
      taskTitle: "tu",
      taskId: "u",
      needsUser: true,
      addressByName: true,
    });
    await tick();

    // Drain everything.
    for (let i = 0; i < 10 && speech.inFlight > 0; i++) {
      speech.finishOne();
      await tick();
    }

    expect(speech.spoken).toContain("PostHog task 'tu' — Hey Jon, urgent");
    // Some routine lines were dropped (didn't speak all five).
    const routineSpoken = speech.spoken.filter((s) => /— r\d$/.test(s)).length;
    expect(routineSpoken).toBeLessThan(5);
  });
});
