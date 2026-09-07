import type { Readable, Writable } from "node:stream";
import { ReadableStream, WritableStream } from "node:stream/web";
import { serializeError } from "@posthog/shared";
import type { Logger } from "./logger";

export class Pushable<T> implements AsyncIterable<T> {
  private queue: T[] = [];
  private resolvers: ((value: IteratorResult<T>) => void)[] = [];
  private done = false;

  push(item: T) {
    const resolve = this.resolvers.shift();
    if (resolve) {
      resolve({ value: item, done: false });
    } else {
      this.queue.push(item);
    }
  }

  end() {
    this.done = true;
    for (const resolve of this.resolvers) {
      resolve({ value: undefined as unknown as T, done: true });
    }
    this.resolvers = [];
  }

  [Symbol.asyncIterator](): AsyncIterator<T> {
    return {
      next: (): Promise<IteratorResult<T>> => {
        if (this.queue.length > 0) {
          const value = this.queue.shift() as T;
          return Promise.resolve({ value, done: false });
        }
        if (this.done) {
          return Promise.resolve({
            value: undefined as unknown as T,
            done: true,
          });
        }
        return new Promise<IteratorResult<T>>((resolve) => {
          this.resolvers.push(resolve);
        });
      },
    };
  }
}

export type StreamPair = {
  readable: globalThis.ReadableStream<Uint8Array>;
  writable: globalThis.WritableStream<Uint8Array>;
};

export type BidirectionalStreamPair = {
  client: StreamPair;
  agent: StreamPair;
};

function pushableToReadableStream(
  pushable: Pushable<Uint8Array>,
): globalThis.ReadableStream<Uint8Array> {
  const iterator = pushable[Symbol.asyncIterator]();
  return new ReadableStream<Uint8Array>({
    async pull(controller) {
      const { value, done } = await iterator.next();
      if (done) {
        controller.close();
      } else {
        controller.enqueue(value);
      }
    },
  }) as unknown as globalThis.ReadableStream<Uint8Array>;
}

export function createBidirectionalStreams(): BidirectionalStreamPair {
  const clientToAgentPushable = new Pushable<Uint8Array>();
  const agentToClientPushable = new Pushable<Uint8Array>();

  const clientToAgentReadable = pushableToReadableStream(clientToAgentPushable);
  const agentToClientReadable = pushableToReadableStream(agentToClientPushable);

  const clientToAgentWritable = new WritableStream<Uint8Array>({
    write(chunk) {
      clientToAgentPushable.push(chunk);
    },
    close() {
      clientToAgentPushable.end();
    },
  }) as globalThis.WritableStream<Uint8Array>;

  const agentToClientWritable = new WritableStream<Uint8Array>({
    write(chunk) {
      agentToClientPushable.push(chunk);
    },
    close() {
      agentToClientPushable.end();
    },
  }) as globalThis.WritableStream<Uint8Array>;

  return {
    client: {
      readable: agentToClientReadable,
      writable: clientToAgentWritable,
    },
    agent: {
      readable: clientToAgentReadable,
      writable: agentToClientWritable,
    },
  };
}

type MessageCallback = (line: string) => void;

export interface TappedStreamOptions {
  onMessage: MessageCallback;
  logger?: Logger;
}

export function createTappedWritableStream(
  underlying: WritableStream<Uint8Array>,
  options: TappedStreamOptions,
): WritableStream<Uint8Array> {
  const { onMessage, logger } = options;
  const decoder = new TextDecoder();
  let buffer = "";
  let messageCount = 0;
  let droppedWriteCount = 0;

  return new WritableStream({
    async write(chunk: Uint8Array) {
      buffer += decoder.decode(chunk, { stream: true });

      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";

      for (const line of lines) {
        if (!line.trim()) continue;
        messageCount++;

        onMessage(line);
      }

      try {
        const writer = underlying.getWriter();
        await writer.write(chunk);
        writer.releaseLock();
      } catch (err) {
        // Stream may be closed if subprocess crashed - log but don't throw
        droppedWriteCount++;
        logger?.error("ACP write error", {
          errorDetail: serializeError(err),
          messageCount,
          droppedWriteCount,
          droppedBytes: chunk.byteLength,
        });
      }
    },
    async close() {
      try {
        const writer = underlying.getWriter();
        await writer.close();
        writer.releaseLock();
      } catch {
        // Stream may already be closed
      }
    },
    async abort(reason: unknown) {
      logger?.warn("Tapped stream aborted", { reason });
      try {
        const writer = underlying.getWriter();
        await writer.abort(reason);
        writer.releaseLock();
      } catch {
        // Stream may already be closed
      }
    },
  });
}

export function nodeReadableToWebReadable(
  nodeStream: Readable,
): globalThis.ReadableStream<Uint8Array> {
  return new ReadableStream<Uint8Array>({
    start(controller) {
      nodeStream.on("data", (chunk: Buffer) => {
        controller.enqueue(new Uint8Array(chunk));
      });
      nodeStream.on("end", () => {
        controller.close();
      });
      nodeStream.on("error", (err) => {
        controller.error(err);
      });
    },
    cancel() {
      nodeStream.destroy();
    },
  }) as unknown as globalThis.ReadableStream<Uint8Array>;
}

export function nodeWritableToWebWritable(
  nodeStream: Writable,
): globalThis.WritableStream<Uint8Array> {
  return new WritableStream<Uint8Array>({
    write(chunk) {
      return new Promise((resolve, reject) => {
        const ok = nodeStream.write(Buffer.from(chunk), (err) => {
          if (err) reject(err);
        });
        if (ok) {
          resolve();
        } else {
          nodeStream.once("drain", resolve);
        }
      });
    },
    close() {
      return new Promise((resolve) => {
        nodeStream.end(resolve);
      });
    },
    abort(reason) {
      nodeStream.destroy(
        reason instanceof Error ? reason : new Error(String(reason)),
      );
    },
  }) as globalThis.WritableStream<Uint8Array>;
}
