import { type Operation, TRPCClientError, type TRPCLink } from "@trpc/client";
import {
  getTransformer,
  type TransformerOptions,
} from "@trpc/client/unstable-internals";
import type {
  AnyTRPCRouter,
  inferRouterContext,
  inferTRPCClientTypes,
  TRPCProcedureType,
} from "@trpc/server";
import { type Observer, observable } from "@trpc/server/observable";
import type { TRPCResponseMessage } from "@trpc/server/rpc";
import type { RendererGlobalElectronTRPC } from "../types";
import { transformResult } from "./utils";

type ScopedOperation = Omit<Operation, "id"> & { id: string };

type IPCCallbackResult<TRouter extends AnyTRPCRouter = AnyTRPCRouter> =
  TRPCResponseMessage<unknown, inferRouterContext<TRouter>>;

type IPCCallbacks<TRouter extends AnyTRPCRouter = AnyTRPCRouter> = Observer<
  IPCCallbackResult<TRouter>,
  TRPCClientError<TRouter>
>;

type IPCRequest = {
  type: TRPCProcedureType;
  callbacks: IPCCallbacks;
  op: ScopedOperation;
};

const getElectronTRPC = () => {
  const electronTRPC: RendererGlobalElectronTRPC = (
    globalThis as unknown as { electronTRPC: RendererGlobalElectronTRPC }
  ).electronTRPC;

  if (!electronTRPC) {
    throw new Error(
      "Could not find `electronTRPC` global. Check that `exposeElectronTRPC` has been called in your preload file.",
    );
  }

  return electronTRPC;
};

class IPCClient {
  #pendingRequests = new Map<string | number, IPCRequest>();
  #electronTRPC = getElectronTRPC();
  #sessionId = crypto.randomUUID();

  constructor() {
    this.#electronTRPC.onMessage((response: TRPCResponseMessage) => {
      this.#handleResponse(response);
    });
  }

  #handleResponse(response: TRPCResponseMessage) {
    const request = response.id && this.#pendingRequests.get(response.id);
    if (!request) {
      return;
    }

    request.callbacks.next(response);

    if ("result" in response && response.result.type === "stopped") {
      request.callbacks.complete();
    }
  }

  request(op: Operation, callbacks: IPCCallbacks) {
    const { type, signal } = op;
    const scopedId = `${this.#sessionId}:${op.id}`;
    const scopedOp = { ...op, id: scopedId };

    if (signal?.aborted) {
      callbacks.error(
        TRPCClientError.from(
          new DOMException("The operation was aborted.", "AbortError"),
        ),
      );
      return () => {};
    }

    this.#pendingRequests.set(scopedId, {
      type,
      callbacks,
      op: scopedOp,
    });

    this.#electronTRPC.sendMessage({
      method: "request",
      operation: scopedOp as unknown as Operation,
    });

    const onAbort = () => {
      if (!this.#pendingRequests.has(scopedId)) return;
      this.#electronTRPC.sendMessage({
        id: scopedId,
        method: "operation.cancel",
      });
    };
    signal?.addEventListener("abort", onAbort);

    return () => {
      const callbacks = this.#pendingRequests.get(scopedId)?.callbacks;

      this.#pendingRequests.delete(scopedId);
      signal?.removeEventListener("abort", onAbort);

      callbacks?.complete();

      if (type === "subscription") {
        this.#electronTRPC.sendMessage({
          id: scopedId,
          method: "subscription.stop",
        });
      }
    };
  }
}

export type IPCLinkOptions<TRouter extends AnyTRPCRouter> = TransformerOptions<
  inferTRPCClientTypes<TRouter>
>;

export function ipcLink<TRouter extends AnyTRPCRouter>(
  opts?: IPCLinkOptions<TRouter>,
): TRPCLink<TRouter> {
  return () => {
    const client = new IPCClient();
    const transformer = getTransformer(opts?.transformer);

    return ({ op }) => {
      return observable((observer) => {
        op.input = transformer.input.serialize(op.input);

        const unsubscribe = client.request(op, {
          error(err) {
            observer.error(err as TRPCClientError<TRouter>);
            unsubscribe();
          },
          complete() {
            observer.complete();
          },
          next(response) {
            const transformed = transformResult(response, transformer.output);

            if (!transformed.ok) {
              observer.error(TRPCClientError.from(transformed.error));
              return;
            }

            observer.next({ result: transformed.result });

            if (op.type !== "subscription") {
              unsubscribe();
              observer.complete();
            }
          },
        });

        return () => {
          unsubscribe();
        };
      });
    };
  };
}
