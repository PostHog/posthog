import type {
  AnyTRPCRouter,
  inferRouterError,
  TRPCCombinedDataTransformer,
} from "@trpc/server";
import type {
  TRPCResponse,
  TRPCResponseMessage,
  TRPCResultMessage,
} from "@trpc/server/rpc";

// from @trpc/client/src/links/internals/transformResult
// FIXME:
// - the generics here are probably unnecessary
// - the RPC-spec could probably be simplified to combine HTTP + WS
/** @internal */
export function transformResult<TRouter extends AnyTRPCRouter, TOutput>(
  response:
    | TRPCResponseMessage<TOutput, inferRouterError<TRouter>>
    | TRPCResponse<TOutput, inferRouterError<TRouter>>,
  transformer: TRPCCombinedDataTransformer["output"],
) {
  if ("error" in response) {
    const error = transformer.deserialize(
      response.error,
    ) as inferRouterError<TRouter>;
    return {
      ok: false,
      error: {
        ...response,
        error,
      },
    } as const;
  }

  const result = {
    ...response.result,
    ...((!response.result.type || response.result.type === "data") && {
      type: "data",
      data: transformer.deserialize(response.result.data) as unknown,
    }),
  } as TRPCResultMessage<TOutput>["result"];
  return { ok: true, result } as const;
}
