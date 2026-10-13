import type { CloudTaskUpdatePayload } from "@posthog/shared/domain-types";
import { describe, expect, it, vi } from "vitest";
import {
  type CloudTaskSubscriptionHandlers,
  SharedCloudTaskSubscriptions,
} from "./sharedCloudTaskSubscriptions";

type TransportHandlers = CloudTaskSubscriptionHandlers & {
  onComplete: () => void;
};

function createTransport() {
  const opened: Array<{
    taskId: string;
    runId: string;
    handlers: TransportHandlers;
    unsubscribe: ReturnType<typeof vi.fn>;
  }> = [];
  const unwatch = vi.fn(() => Promise.resolve());
  return {
    opened,
    unwatch,
    subscribe: vi.fn(
      (taskId: string, runId: string, handlers: TransportHandlers) => {
        const unsubscribe = vi.fn();
        opened.push({ taskId, runId, handlers, unsubscribe });
        return unsubscribe;
      },
    ),
  };
}

function createHandlers() {
  return {
    onUpdate: vi.fn(),
    onError: vi.fn(),
    onStarted: vi.fn(),
  };
}

const statusUpdate: CloudTaskUpdatePayload = {
  taskId: "task-1",
  runId: "run-1",
  kind: "status",
  status: "in_progress",
  stage: null,
  output: null,
  errorMessage: null,
  branch: null,
};

describe("SharedCloudTaskSubscriptions", () => {
  it("rides every subscriber of one run on a single transport subscription", () => {
    const transport = createTransport();
    const shared = new SharedCloudTaskSubscriptions(transport);
    const first = createHandlers();
    const second = createHandlers();
    const otherRun = createHandlers();

    shared.subscribe("task-1", "run-1", first);
    shared.subscribe("task-1", "run-1", second);
    shared.subscribe("task-1", "run-2", otherRun);

    expect(transport.subscribe).toHaveBeenCalledTimes(2);
    expect(transport.opened.map((entry) => entry.runId)).toEqual([
      "run-1",
      "run-2",
    ]);

    transport.opened[0].handlers.onStarted();
    transport.opened[0].handlers.onUpdate(statusUpdate);

    expect(first.onStarted).toHaveBeenCalledTimes(1);
    expect(second.onStarted).toHaveBeenCalledTimes(1);
    expect(first.onUpdate).toHaveBeenCalledWith(statusUpdate);
    expect(second.onUpdate).toHaveBeenCalledWith(statusUpdate);
    expect(otherRun.onStarted).not.toHaveBeenCalled();
    expect(otherRun.onUpdate).not.toHaveBeenCalled();
  });

  it("starts a late subscriber and balances its watch when it leaves before the others", async () => {
    const transport = createTransport();
    const shared = new SharedCloudTaskSubscriptions(transport);
    const first = createHandlers();
    const late = createHandlers();

    const unsubscribeFirst = shared.subscribe("task-1", "run-1", first);
    transport.opened[0].handlers.onStarted();

    const unsubscribeLate = shared.subscribe("task-1", "run-1", late);
    expect(late.onStarted).not.toHaveBeenCalled();
    await Promise.resolve();
    expect(late.onStarted).toHaveBeenCalledTimes(1);
    expect(transport.subscribe).toHaveBeenCalledTimes(1);

    unsubscribeLate();
    expect(transport.unwatch).toHaveBeenCalledWith("task-1", "run-1");
    expect(transport.opened[0].unsubscribe).not.toHaveBeenCalled();

    unsubscribeFirst();
    expect(transport.opened[0].unsubscribe).toHaveBeenCalledTimes(1);
    // The host unwatches the last subscriber itself when the subscription ends.
    expect(transport.unwatch).toHaveBeenCalledTimes(1);
  });

  it("does not unwatch for a subscriber that left before the transport started", () => {
    const transport = createTransport();
    const shared = new SharedCloudTaskSubscriptions(transport);
    const first = createHandlers();
    const second = createHandlers();

    shared.subscribe("task-1", "run-1", first);
    const unsubscribeSecond = shared.subscribe("task-1", "run-1", second);

    unsubscribeSecond();
    transport.opened[0].handlers.onStarted();

    expect(transport.unwatch).not.toHaveBeenCalled();
    expect(second.onStarted).not.toHaveBeenCalled();
    expect(first.onStarted).toHaveBeenCalledTimes(1);
  });

  it("reports a transport error to every subscriber and opens a fresh subscription afterwards", () => {
    const transport = createTransport();
    const shared = new SharedCloudTaskSubscriptions(transport);
    const first = createHandlers();
    const second = createHandlers();
    const error = new Error("stream closed");

    shared.subscribe("task-1", "run-1", first);
    shared.subscribe("task-1", "run-1", second);
    transport.opened[0].handlers.onError(error);

    expect(first.onError).toHaveBeenCalledWith(error);
    expect(second.onError).toHaveBeenCalledWith(error);

    const replacement = createHandlers();
    shared.subscribe("task-1", "run-1", replacement);
    expect(transport.subscribe).toHaveBeenCalledTimes(2);

    transport.opened[1].handlers.onUpdate(statusUpdate);
    expect(replacement.onUpdate).toHaveBeenCalledWith(statusUpdate);
    expect(first.onUpdate).not.toHaveBeenCalled();
  });
});
