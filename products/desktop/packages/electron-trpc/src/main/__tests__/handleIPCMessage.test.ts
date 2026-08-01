import { EventEmitter } from "node:events";
import * as trpc from "@trpc/server";
import { observable } from "@trpc/server/observable";
import type { IpcMainEvent } from "electron";
import { describe, expect, type MockedFunction, test, vi } from "vitest";
import { z } from "zod";

import { handleIPCMessage } from "../handleIPCMessage";

interface MockEvent {
  reply: MockedFunction<(channel: string, data: unknown) => void>;
  sender: {
    isDestroyed: () => boolean;
    on: (event: string, cb: () => void) => void;
  };
}
const makeEvent = (event: MockEvent) =>
  event as unknown as IpcMainEvent & Pick<MockEvent, "reply">;

const t = trpc.initTRPC.create();
const testRouter = t.router({
  testQuery: t.procedure
    .input(
      z.object({
        id: z.string(),
      }),
    )
    .query(({ input }) => {
      return { id: input.id, isTest: true };
    }),
});

describe("api", () => {
  test("handles queries", async () => {
    const event = makeEvent({
      reply: vi.fn(),
      sender: {
        isDestroyed: () => false,
        on: () => {},
      },
    });

    await handleIPCMessage({
      createContext: async () => ({}),
      event,
      internalId: "1-1:1",
      message: {
        method: "request",
        operation: {
          context: {},
          id: 1,
          input: { id: "test-id" },
          path: "testQuery",
          type: "query",
          signal: undefined,
        },
      },
      router: testRouter,
      operations: new Map(),
    });

    expect(event.reply).toHaveBeenCalledOnce();
    expect(event.reply.mock.lastCall?.[1]).toMatchObject({
      id: 1,
      result: {
        data: {
          id: "test-id",
          isTest: true,
        },
      },
    });
  });

  test("does not respond if sender is gone", async () => {
    const event = makeEvent({
      reply: vi.fn(),
      sender: {
        isDestroyed: () => true,
        on: () => {},
      },
    });

    await handleIPCMessage({
      createContext: async () => ({}),
      event,
      internalId: "1-1:1",
      message: {
        method: "request",
        operation: {
          context: {},
          id: 1,
          input: { id: "test-id" },
          path: "testQuery",
          type: "query",
          signal: undefined,
        },
      },
      router: testRouter,
      operations: new Map(),
    });

    expect(event.reply).not.toHaveBeenCalled();
  });

  test("reports procedure failures through onError and still responds", async () => {
    const failingRouter = t.router({
      failingQuery: t.procedure.query(() => {
        throw new Error("db exploded");
      }),
    });
    const onError = vi.fn();
    const event = makeEvent({
      reply: vi.fn(),
      sender: {
        isDestroyed: () => false,
        on: () => {},
      },
    });

    await handleIPCMessage({
      createContext: async () => ({}),
      event,
      internalId: "1-1:1",
      message: {
        method: "request",
        operation: {
          context: {},
          id: 1,
          input: undefined,
          path: "failingQuery",
          type: "query",
          signal: undefined,
        },
      },
      router: failingRouter,
      operations: new Map(),
      onError,
    });

    expect(onError).toHaveBeenCalledOnce();
    expect(onError.mock.lastCall?.[0]).toMatchObject({
      path: "failingQuery",
      type: "query",
    });
    expect(onError.mock.lastCall?.[0].error.cause?.message).toBe("db exploded");
    expect(event.reply.mock.lastCall?.[1]).toMatchObject({
      id: 1,
      error: expect.anything(),
    });
  });

  test("reports subscription stream failures through onError", async () => {
    const failingSubRouter = t.router({
      failingSubscription: t.procedure.subscription(() =>
        observable((emit) => {
          emit.error(new Error("stream exploded"));
          return () => {};
        }),
      ),
    });
    const onError = vi.fn();
    const event = makeEvent({
      reply: vi.fn(),
      sender: {
        isDestroyed: () => false,
        on: () => {},
      },
    });

    await handleIPCMessage({
      createContext: async () => ({}),
      event,
      internalId: "1-1:1",
      message: {
        method: "request",
        operation: {
          context: {},
          id: 1,
          input: undefined,
          path: "failingSubscription",
          type: "subscription",
          signal: undefined,
        },
      },
      router: failingSubRouter,
      operations: new Map(),
      onError,
    });

    await vi.waitFor(() => {
      expect(onError).toHaveBeenCalledOnce();
    });
    expect(onError.mock.lastCall?.[0]).toMatchObject({
      path: "failingSubscription",
      type: "subscription",
    });
    // The stream error is serialized to the renderer before the final
    // "stopped" message, so it is not necessarily the last reply.
    await vi.waitFor(() => {
      expect(
        event.reply.mock.calls.some(
          ([, payload]) => (payload as { error?: unknown }).error !== undefined,
        ),
      ).toBe(true);
    });
  });

  test("handles subscriptions using observables", async () => {
    const operations = new Map();
    const ee = new EventEmitter();
    const t = trpc.initTRPC.create();
    const testRouter = t.router({
      testSubscription: t.procedure.subscription(() => {
        return observable((emit) => {
          function testResponse() {
            emit.next("test response");
          }

          ee.on("test", testResponse);
          return () => ee.off("test", testResponse);
        });
      }),
    });

    const event = makeEvent({
      reply: vi.fn(),
      sender: {
        isDestroyed: () => false,
        on: () => {},
      },
    });

    expect(ee.listenerCount("test")).toBe(0);

    await handleIPCMessage({
      createContext: async () => ({}),
      message: {
        method: "request",
        operation: {
          context: {},
          id: 1,
          input: undefined,
          path: "testSubscription",
          type: "subscription",
          signal: undefined,
        },
      },
      internalId: "1-1:1",
      operations,
      router: testRouter,
      event,
    });

    expect(ee.listenerCount("test")).toBe(1);
    expect(event.reply).toHaveBeenCalledTimes(1);
    expect(event.reply.mock.lastCall?.[1]).toMatchObject({
      id: 1,
      result: {
        type: "started",
      },
    });

    ee.emit("test");

    await vi.waitFor(() => {
      expect(event.reply).toHaveBeenCalledTimes(2);
      expect(event.reply.mock.lastCall?.[1]).toMatchObject({
        id: 1,
        result: {
          data: "test response",
        },
      });
    });

    await handleIPCMessage({
      createContext: async () => ({}),
      message: {
        method: "subscription.stop",
        id: 1,
      },
      internalId: "1-1:1",
      operations,
      router: testRouter,
      event,
    });

    await vi.waitFor(() => {
      expect(ee.listenerCount("test")).toBe(0);
      expect(event.reply).toHaveBeenCalledTimes(3);
      expect(event.reply.mock.lastCall?.[1]).toMatchObject({
        id: 1,
        result: {
          type: "stopped",
        },
      });
    });
  });

  test("handles subscriptions using async generators", async () => {
    const operations = new Map();
    const t = trpc.initTRPC.create();

    // Simple async generator that yields a single value
    const testRouter = t.router({
      testSubscription: t.procedure.subscription(async function* () {
        yield "test response";
      }),
    });

    const event = makeEvent({
      reply: vi.fn(),
      sender: {
        isDestroyed: () => false,
        on: () => {},
      },
    });

    await handleIPCMessage({
      createContext: async () => ({}),
      message: {
        method: "request",
        operation: {
          context: {},
          id: 1,
          input: undefined,
          path: "testSubscription",
          type: "subscription",
          signal: undefined,
        },
      },
      internalId: "1-1:1",
      operations,
      router: testRouter,
      event,
    });

    // Wait for the generator to yield and complete
    await vi.waitFor(() => {
      // Should have at least: started, data
      expect(event.reply.mock.calls.length).toBeGreaterThanOrEqual(2);
    });

    // First response should be "started"
    expect(event.reply.mock.calls[0][1]).toMatchObject({
      id: 1,
      result: {
        type: "started",
      },
    });

    // Second response should be the yielded data
    expect(event.reply.mock.calls[1][1]).toMatchObject({
      id: 1,
      result: {
        data: "test response",
      },
    });
  });

  test("operation.cancel aborts in-flight mutation signal", async () => {
    const event = makeEvent({
      reply: vi.fn(),
      sender: {
        isDestroyed: () => false,
        on: () => {},
      },
    });

    const signalCaptured = vi.fn();
    const t = trpc.initTRPC.create();
    const cancelRouter = t.router({
      slowMutation: t.procedure.mutation(async ({ signal }) => {
        signalCaptured(signal);
        await new Promise<void>((_resolve, reject) => {
          signal?.addEventListener("abort", () => {
            reject(new Error("aborted"));
          });
        });
        return "should not reach";
      }),
    });

    const operations = new Map();

    const mutationCall = handleIPCMessage({
      createContext: async () => ({}),
      event,
      internalId: "1-1:1",
      message: {
        method: "request",
        operation: {
          context: {},
          id: 1,
          input: undefined,
          path: "slowMutation",
          type: "mutation",
          signal: undefined,
        },
      },
      router: cancelRouter,
      operations,
    });

    await vi.waitFor(() => {
      expect(signalCaptured).toHaveBeenCalled();
    });

    expect(operations.has("1-1:1")).toBe(true);

    await handleIPCMessage({
      createContext: async () => ({}),
      event,
      internalId: "1-1:1",
      message: { method: "operation.cancel", id: 1 },
      router: cancelRouter,
      operations,
    });

    await mutationCall;

    expect(signalCaptured.mock.calls[0][0].aborted).toBe(true);
    expect(event.reply).toHaveBeenCalled();
    const lastResponse = event.reply.mock.lastCall?.[1] as {
      id: number;
      error?: unknown;
    };
    expect(lastResponse).toMatchObject({ id: 1, error: expect.anything() });
    expect(operations.has("1-1:1")).toBe(false);
  });

  test("query removes itself from operations map on success", async () => {
    const event = makeEvent({
      reply: vi.fn(),
      sender: {
        isDestroyed: () => false,
        on: () => {},
      },
    });

    const operations = new Map();

    await handleIPCMessage({
      createContext: async () => ({}),
      event,
      internalId: "1-1:9",
      message: {
        method: "request",
        operation: {
          context: {},
          id: 9,
          input: { id: "test" },
          path: "testQuery",
          type: "query",
          signal: undefined,
        },
      },
      router: testRouter,
      operations,
    });

    expect(operations.has("1-1:9")).toBe(false);
  });

  test("subscription responds using custom serializer", async () => {
    const event = makeEvent({
      reply: vi.fn(),
      sender: {
        isDestroyed: () => false,
        on: () => {},
      },
    });

    const ee = new EventEmitter();

    const t = trpc.initTRPC.create({
      transformer: {
        deserialize: (input: unknown) => {
          const serialized = (input as string).replace(/^serialized:/, "");
          return JSON.parse(serialized);
        },
        serialize: (input) => {
          return `serialized:${JSON.stringify(input)}`;
        },
      },
    });

    const testRouter = t.router({
      testSubscription: t.procedure.subscription(() => {
        return observable((emit) => {
          function testResponse() {
            emit.next("test response");
          }

          ee.on("test", testResponse);
          return () => ee.off("test", testResponse);
        });
      }),
    });

    await handleIPCMessage({
      createContext: async () => ({}),
      message: {
        method: "request",
        operation: {
          context: {},
          id: 1,
          input: undefined,
          path: "testSubscription",
          type: "subscription",
          signal: undefined,
        },
      },
      internalId: "1-1:1",
      operations: new Map(),
      router: testRouter,
      event,
    });

    expect(event.reply).toHaveBeenCalledTimes(1);
    expect(event.reply.mock.lastCall?.[1]).toMatchObject({
      id: 1,
      result: {
        type: "started",
      },
    });

    ee.emit("test");

    await vi.waitFor(() => {
      expect(event.reply).toHaveBeenCalledTimes(2);
      expect(event.reply.mock.lastCall?.[1]).toMatchObject({
        id: 1,
        result: {
          type: "data",
          data: 'serialized:"test response"',
        },
      });
    });
  });
});
