import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  __resetBackgroundJobsForTesting,
  cancelAllBackgroundJobs,
  cancelBackgroundJob,
  listBackgroundJobs,
  startBackgroundJob,
} from "./jobs";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function fakePi() {
  const messages: Array<{ message: unknown; options: unknown }> = [];
  return {
    messages,
    pi: {
      sendMessage: (message: unknown, options?: unknown) => {
        messages.push({ message, options });
      },
    },
  };
}

describe("startBackgroundJob", () => {
  beforeEach(() => {
    __resetBackgroundJobsForTesting();
  });

  it("returns an immediate ack without waiting for work to settle", async () => {
    const { pi } = fakePi();
    const work = deferred<string>();
    const start = startBackgroundJob({
      pi,
      label: "test job",
      work: () => work.promise,
      onSuccess: (result) => result,
    });

    expect(start.ack).toContain("test job");
    expect(start.jobId).toBeTruthy();
    expect(listBackgroundJobs()).toEqual([
      expect.objectContaining({ jobId: start.jobId, label: "test job" }),
    ]);

    work.resolve("done");
    await vi.waitFor(() => expect(listBackgroundJobs()).toEqual([]));
  });

  it("delivers success via sendMessage with steer + triggerTurn", async () => {
    const { pi, messages } = fakePi();
    startBackgroundJob({
      pi,
      label: "audit",
      work: async () => 42,
      onSuccess: (n) => `found ${n} issues`,
    });

    await vi.waitFor(() => expect(messages).toHaveLength(1));
    const { message, options } = messages[0];
    expect(options).toEqual({ deliverAs: "steer", triggerTurn: true });
    expect((message as { customType: string }).customType).toBe(
      "background-job",
    );
    expect((message as { content: string }).content).toContain(
      "found 42 issues",
    );
    expect((message as { details: { status: string } }).details.status).toBe(
      "completed",
    );
  });

  it("delivers failure via onFailure, defaulting to the error message", async () => {
    const { pi, messages } = fakePi();
    startBackgroundJob({
      pi,
      label: "broken",
      work: async () => {
        throw new Error("boom");
      },
      onSuccess: () => "unreachable",
    });

    await vi.waitFor(() => expect(messages).toHaveLength(1));
    const { message } = messages[0];
    expect((message as { content: string }).content).toContain("boom");
    expect((message as { details: { status: string } }).details.status).toBe(
      "failed",
    );
  });

  it("cancelBackgroundJob aborts the work signal and reports cancelled, not failed", async () => {
    const { pi, messages } = fakePi();
    const start = startBackgroundJob({
      pi,
      label: "cancel me",
      work: (signal) =>
        new Promise((_resolve, reject) => {
          signal.addEventListener("abort", () => reject(new Error("aborted")));
        }),
      onSuccess: () => "unreachable",
    });

    expect(cancelBackgroundJob(start.jobId)).toBe(true);
    await vi.waitFor(() => expect(messages).toHaveLength(1));
    expect(
      (messages[0].message as { details: { status: string } }).details.status,
    ).toBe("cancelled");
  });

  it("cancelBackgroundJob returns false for an unknown job id", () => {
    expect(cancelBackgroundJob("does-not-exist")).toBe(false);
  });

  it("propagates an already-aborted upstream signal immediately", async () => {
    const { pi, messages } = fakePi();
    const controller = new AbortController();
    controller.abort();
    startBackgroundJob({
      pi,
      label: "pre-aborted",
      signal: controller.signal,
      work: (signal) =>
        new Promise((_resolve, reject) => {
          if (signal.aborted) reject(new Error("already aborted"));
        }),
      onSuccess: () => "unreachable",
    });

    await vi.waitFor(() => expect(messages).toHaveLength(1));
    expect(
      (messages[0].message as { details: { status: string } }).details.status,
    ).toBe("cancelled");
  });

  it("cancelAllBackgroundJobs aborts every running job", async () => {
    const { pi, messages } = fakePi();
    for (const label of ["a", "b", "c"]) {
      startBackgroundJob({
        pi,
        label,
        work: (signal) =>
          new Promise((_resolve, reject) => {
            signal.addEventListener("abort", () =>
              reject(new Error("aborted")),
            );
          }),
        onSuccess: () => "unreachable",
      });
    }
    expect(listBackgroundJobs()).toHaveLength(3);

    cancelAllBackgroundJobs();

    await vi.waitFor(() => expect(messages).toHaveLength(3));
    for (const { message } of messages) {
      expect((message as { details: { status: string } }).details.status).toBe(
        "cancelled",
      );
    }
  });

  it("listBackgroundJobs is sorted by start order", async () => {
    const { pi } = fakePi();
    const work = deferred<void>();
    startBackgroundJob({
      pi,
      label: "first",
      work: () => work.promise,
      onSuccess: () => "",
    });
    startBackgroundJob({
      pi,
      label: "second",
      work: () => work.promise,
      onSuccess: () => "",
    });

    expect(listBackgroundJobs().map((j) => j.label)).toEqual([
      "first",
      "second",
    ]);
  });
});
