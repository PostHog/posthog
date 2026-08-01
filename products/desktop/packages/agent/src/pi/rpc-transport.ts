import type {
  AgentSessionEvent,
  RpcClient,
  RpcCommand,
  RpcResponse,
} from "@earendil-works/pi-coding-agent";
import { z } from "zod/v4";

export type { RpcCommand, RpcResponse } from "@earendil-works/pi-coding-agent";

export const piRpcCommandSchema = z
  .object({
    id: z.string().optional(),
    type: z.string().min(1),
  })
  .loose()
  .transform((command) => command as RpcCommand);

export const piRpcResponseSchema = z.discriminatedUnion("success", [
  z
    .object({
      id: z.string().optional(),
      type: z.literal("response"),
      command: z.string(),
      success: z.literal(true),
      data: z.unknown().optional(),
    })
    .loose(),
  z
    .object({
      id: z.string().optional(),
      type: z.literal("response"),
      command: z.string(),
      success: z.literal(false),
      error: z.string(),
    })
    .loose(),
]);

export function parsePiRpcResponse(value: unknown): RpcResponse {
  return piRpcResponseSchema.parse(value) as RpcResponse;
}

export interface PiRpcTransport {
  request(command: RpcCommand): Promise<unknown>;
  onEvent?(listener: (event: AgentSessionEvent) => void): () => void;
  start?(): Promise<void>;
  stop?(): Promise<void>;
}

interface RpcClientInternals {
  send(command: RpcCommand): Promise<RpcResponse>;
}

export function sendPiRpcCommand(
  client: RpcClient,
  command: RpcCommand,
): Promise<RpcResponse> {
  const internals = client as unknown as RpcClientInternals;
  return internals.send(command);
}
