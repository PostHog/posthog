import type {
  Sketchpad,
  SketchpadAppendOpsInput,
  SketchpadAppendOpsResult,
  SketchpadCompiledFragment,
  SketchpadOpsPage,
  SketchpadPresenceInput,
  SketchpadStreamEvent,
  SketchpadSummary,
} from "@posthog/shared";
import type { SketchpadMetadataPatch } from "./sketchpadSchemas";

export const SKETCHPAD_BOARDS_SERVICE = Symbol.for(
  "posthog.core.sketchpad.service",
);

export interface ISketchpadService {
  compiled(
    id: string,
    refs: string[],
    signal?: AbortSignal,
  ): Promise<Record<string, SketchpadCompiledFragment>>;
  list(channelId?: string): Promise<SketchpadSummary[]>;
  get(id: string): Promise<Sketchpad>;
  create(channelId: string, name: string): Promise<Sketchpad>;
  update(id: string, patch: SketchpadMetadataPatch): Promise<void>;
  remove(id: string): Promise<void>;
  opsSince(
    id: string,
    since: number,
    limit?: number,
  ): Promise<SketchpadOpsPage>;
  appendOps(
    id: string,
    input: SketchpadAppendOpsInput,
  ): Promise<SketchpadAppendOpsResult>;
}

export const SKETCHPAD_STREAM_SERVICE = Symbol.for(
  "posthog.core.sketchpad.streamService",
);

export interface ISketchpadStreamService {
  streamSketchpad(
    sketchpadId: string,
    signal?: AbortSignal,
  ): AsyncGenerator<SketchpadStreamEvent>;
  sendPresence(
    sketchpadId: string,
    input: SketchpadPresenceInput,
  ): Promise<void>;
}
