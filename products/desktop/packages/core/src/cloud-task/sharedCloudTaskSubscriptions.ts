import type { CloudTaskUpdatePayload } from "@posthog/shared/domain-types";

export interface CloudTaskSubscriptionHandlers {
  onUpdate: (update: CloudTaskUpdatePayload) => void;
  onError: (error: unknown) => void;
  onStarted: () => void;
}

/**
 * The single host subscription a channel rides on. `onComplete` fires when the
 * host ends the stream without an error.
 */
export interface CloudTaskSubscriptionTransport {
  subscribe(
    taskId: string,
    runId: string,
    handlers: CloudTaskSubscriptionHandlers & { onComplete: () => void },
  ): () => void;
  unwatch(taskId: string, runId: string): Promise<void>;
}

interface Listener {
  handlers: CloudTaskSubscriptionHandlers;
  started: boolean;
}

interface Channel {
  listeners: Set<Listener>;
  started: boolean;
  unsubscribe: () => void;
}

function channelKey(taskId: string, runId: string): string {
  return `${taskId}:${runId}`;
}

/**
 * Fans one host subscription per task run out to every local subscriber.
 *
 * The host serializes each update once per subscription it holds, so N
 * subscribers to one run would cost N serializations of every transcript
 * snapshot. Sharing the subscription makes that one.
 *
 * Contract kept from the unshared client: each subscriber calls `watch()` from
 * `onStarted`, and the host unwatches once when the shared subscription ends.
 * A subscriber that leaves while others stay therefore unwatches explicitly,
 * so the host's subscriber count still returns to zero.
 */
export class SharedCloudTaskSubscriptions {
  private readonly channels = new Map<string, Channel>();

  constructor(private readonly transport: CloudTaskSubscriptionTransport) {}

  subscribe(
    taskId: string,
    runId: string,
    handlers: CloudTaskSubscriptionHandlers,
  ): () => void {
    const key = channelKey(taskId, runId);
    const channel = this.channels.get(key) ?? this.open(key, taskId, runId);
    const listener: Listener = { handlers, started: false };
    channel.listeners.add(listener);

    if (channel.started) {
      // A late subscriber gets the same start signal the others got, after
      // `subscribe` has returned, as the transport would deliver it.
      queueMicrotask(() => {
        if (channel.listeners.has(listener) && !listener.started) {
          listener.started = true;
          handlers.onStarted();
        }
      });
    }

    return () => {
      if (!channel.listeners.delete(listener)) {
        return;
      }
      if (channel.listeners.size === 0) {
        if (this.channels.get(key) === channel) {
          this.channels.delete(key);
        }
        channel.unsubscribe();
        return;
      }
      if (listener.started) {
        void this.transport.unwatch(taskId, runId).catch(() => {});
      }
    };
  }

  private open(key: string, taskId: string, runId: string): Channel {
    const channel: Channel = {
      listeners: new Set(),
      started: false,
      unsubscribe: () => {},
    };
    this.channels.set(key, channel);

    const drop = (): void => {
      if (this.channels.get(key) === channel) {
        this.channels.delete(key);
      }
    };

    channel.unsubscribe = this.transport.subscribe(taskId, runId, {
      onStarted: () => {
        channel.started = true;
        for (const listener of [...channel.listeners]) {
          if (listener.started) continue;
          listener.started = true;
          listener.handlers.onStarted();
        }
      },
      onUpdate: (update) => {
        for (const listener of [...channel.listeners]) {
          listener.handlers.onUpdate(update);
        }
      },
      onError: (error) => {
        // The host subscription is dead; the next subscriber opens a new one.
        // Existing listeners keep their own recovery, as they did unshared.
        drop();
        for (const listener of [...channel.listeners]) {
          listener.handlers.onError(error);
        }
      },
      onComplete: drop,
    });

    return channel;
  }
}
