import type { TRPCError } from "@trpc/server";
import type { IpcMainInvokeEvent } from "electron";

export interface CreateContextOptions {
  event: IpcMainInvokeEvent;
}

export interface ProcedureErrorPayload {
  error: TRPCError;
  path: string | undefined;
  type: "query" | "mutation" | "subscription";
  input: unknown;
}

/**
 * Called whenever procedure resolution fails. Errors are otherwise only
 * serialized back to the renderer, leaving no trace in main process logs.
 */
export type OnProcedureError = (payload: ProcedureErrorPayload) => void;
