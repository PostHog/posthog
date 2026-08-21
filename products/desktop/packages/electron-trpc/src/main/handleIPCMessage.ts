import type { AnyTRPCRouter, inferRouterContext } from "@trpc/server";
import {
  callTRPCProcedure,
  getErrorShape,
  getTRPCErrorFromUnknown,
  isTrackedEnvelope,
  TRPCError,
  transformTRPCResponse,
} from "@trpc/server";
import {
  isObservable,
  observableToAsyncIterable,
} from "@trpc/server/observable";
import type { TRPCResponseMessage, TRPCResultMessage } from "@trpc/server/rpc";
import type { IpcMainEvent } from "electron";
import { ELECTRON_TRPC_CHANNEL } from "../constants";
import type { ETRPCRequest } from "../types";
import { Unpromise } from "../vendor/unpromise";
import type { CreateContextOptions, OnProcedureError } from "./types";
import { isAsyncIterable, iteratorResource, run } from "./utils";

export async function handleIPCMessage<TRouter extends AnyTRPCRouter>({
  router,
  createContext,
  internalId,
  message,
  event,
  operations,
  onError,
}: {
  router: TRouter;
  createContext?: (
    opts: CreateContextOptions,
  ) => Promise<inferRouterContext<TRouter>>;
  internalId: string;
  message: ETRPCRequest;
  event: IpcMainEvent;
  operations: Map<string, AbortController>;
  onError?: OnProcedureError;
}) {
  if (
    message.method === "subscription.stop" ||
    message.method === "operation.cancel"
  ) {
    operations.get(internalId)?.abort();
    return;
  }

  const { type, input: serializedInput, path, id } = message.operation;
  const input = serializedInput
    ? router._def._config.transformer.input.deserialize(serializedInput)
    : undefined;

  const abortController = new AbortController();

  if (operations.has(internalId)) {
    const error = getTRPCErrorFromUnknown(
      new TRPCError({
        message: `Duplicate id ${internalId}`,
        code: "BAD_REQUEST",
      }),
    );
    if (event.sender.isDestroyed()) return;
    event.reply(
      ELECTRON_TRPC_CHANNEL,
      transformTRPCResponse(router._def._config, {
        id,
        error: getErrorShape({
          config: router._def._config,
          error,
          type,
          path,
          input,
          ctx: {},
        }),
      }),
    );
    return;
  }
  operations.set(internalId, abortController);

  const ctx = (await createContext?.({ event })) ?? {};

  const respond = (response: TRPCResponseMessage) => {
    if (event.sender.isDestroyed()) return;
    event.reply(
      ELECTRON_TRPC_CHANNEL,
      transformTRPCResponse(router._def._config, response),
    );
  };

  try {
    const result = await callTRPCProcedure({
      ctx,
      path,
      router,
      getRawInput: async () => input,
      type,
      signal: abortController.signal,
    });

    const isIterableResult = isAsyncIterable(result) || isObservable(result);

    if (type !== "subscription") {
      if (isIterableResult) {
        throw new TRPCError({
          code: "UNSUPPORTED_MEDIA_TYPE",
          message: `Cannot return an async iterable or observable from a ${type} procedure.`,
        });
      }

      respond({
        id,
        result: {
          type: "data",
          data: result,
        },
      });
      operations.delete(internalId);
      return;
    }

    if (!isIterableResult) {
      throw new TRPCError({
        message: `Subscription ${path} did not return an observable or a AsyncGenerator`,
        code: "INTERNAL_SERVER_ERROR",
      });
    }

    const iterable = isObservable(result)
      ? observableToAsyncIterable(result, abortController.signal)
      : result;

    run(async () => {
      await using iterator = iteratorResource(iterable);

      const abortPromise = new Promise<"abort">((resolve) => {
        abortController.signal.onabort = () => resolve("abort");
      });
      // We need those declarations outside the loop for garbage collection reasons. If they
      // were declared inside, they would not be freed until the next value is present.
      let next:
        | null
        | TRPCError
        | Awaited<typeof abortPromise | ReturnType<(typeof iterator)["next"]>>;
      let result: null | TRPCResultMessage<unknown>["result"];

      while (true) {
        next = await Unpromise.race([
          iterator.next().catch(getTRPCErrorFromUnknown),
          abortPromise,
        ]);

        if (next === "abort") {
          await iterator.return?.();
          break;
        }
        if (next instanceof Error) {
          const error = getTRPCErrorFromUnknown(next);
          onError?.({ error, path, type, input });
          respond({
            id,
            error: getErrorShape({
              config: router._def._config,
              error,
              type,
              path,
              input,
              ctx,
            }),
          });
          break;
        }
        if (next.done) {
          break;
        }

        result = {
          type: "data",
          data: next.value,
        };

        if (isTrackedEnvelope(next.value)) {
          const [id, data] = next.value;
          result.id = id;
          result.data = {
            id,
            data,
          };
        }

        respond({
          id,
          result,
        });

        // free up references for garbage collection
        next = null;
        result = null;
      }

      respond({
        id,
        result: {
          type: "stopped",
        },
      });
      operations.delete(internalId);
    }).catch((cause) => {
      const error = getTRPCErrorFromUnknown(cause);
      onError?.({ error, path, type, input });
      respond({
        id,
        error: getErrorShape({
          config: router._def._config,
          error,
          type,
          path,
          input,
          ctx,
        }),
      });
      abortController.abort();
      operations.delete(internalId);
    });

    respond({
      id,
      result: {
        type: "started",
      },
    });
  } catch (cause) {
    operations.delete(internalId);
    const error: TRPCError = getTRPCErrorFromUnknown(cause);
    onError?.({ error, path, type, input });

    return respond({
      id,
      error: getErrorShape({
        config: router._def._config,
        error,
        type,
        path,
        input,
        ctx,
      }),
    });
  }
}
