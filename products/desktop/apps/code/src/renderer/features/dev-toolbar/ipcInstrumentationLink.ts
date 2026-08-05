import type { TRPCLink } from "@trpc/client";
import { observable, tap } from "@trpc/server/observable";
import type { AnyRouter } from "@trpc/server/unstable-core-do-not-import";
import { useDevFlagsStore } from "./devFlagsStore";
import { type IpcOpType, useIpcMetricsStore } from "./ipcMetricsStore";

function byteLength(value: unknown): number {
  if (value === undefined) return 0;
  try {
    return new TextEncoder().encode(JSON.stringify(value)).byteLength;
  } catch {
    return 0;
  }
}

export function ipcInstrumentationLink<
  TRouter extends AnyRouter = AnyRouter,
>(): TRPCLink<TRouter> {
  return () =>
    ({ op, next }) => {
      if (!useDevFlagsStore.getState().devMode) {
        return next(op);
      }
      return observable((observer) => {
        const start = performance.now();
        const startedAt = Date.now();
        const inputBytes = byteLength(op.input);
        let outputBytes = 0;
        let ended = false;
        const store = useIpcMetricsStore.getState();
        store.recordStart();

        function finalize(ok: boolean) {
          if (ended) return;
          ended = true;
          useIpcMetricsStore.getState().recordEnd({
            path: op.path,
            type: op.type as IpcOpType,
            rttMs: performance.now() - start,
            inputBytes,
            outputBytes,
            ok,
            startedAt,
          });
        }

        const subscription = next(op)
          .pipe(
            tap({
              next(envelope) {
                if (
                  envelope &&
                  typeof envelope === "object" &&
                  "result" in envelope &&
                  envelope.result &&
                  typeof envelope.result === "object" &&
                  "data" in envelope.result
                ) {
                  outputBytes += byteLength(
                    (envelope.result as { data: unknown }).data,
                  );
                }
              },
            }),
          )
          .subscribe({
            next(value) {
              observer.next(value);
              if (op.type !== "subscription") {
                finalize(true);
              }
            },
            error(err) {
              finalize(false);
              observer.error(err);
            },
            complete() {
              finalize(true);
              observer.complete();
            },
          });

        return () => {
          finalize(true);
          subscription.unsubscribe();
        };
      });
    };
}
