import type {
  CanvasV2AppendOpsInput,
  CanvasV2AppendOpsResult,
  CanvasV2Board,
  CanvasV2BoardSummary,
  CanvasV2OpsPage,
  CanvasV2PresenceInput,
  CanvasV2StreamEvent,
} from "@posthog/shared";

export const CANVAS_V2_BOARDS_SERVICE = Symbol.for(
  "posthog.core.canvasV2.boardsService",
);

export interface ICanvasV2BoardsService {
  list(channelId: string): Promise<CanvasV2BoardSummary[]>;
  listAll(): Promise<CanvasV2BoardSummary[]>;
  get(id: string): Promise<CanvasV2Board>;
  create(channelId: string, name: string): Promise<CanvasV2Board>;
  rename(id: string, name: string): Promise<CanvasV2Board>;
  setChannel(id: string, channelId: string): Promise<CanvasV2Board>;
  setPinned(id: string, pinned: boolean): Promise<CanvasV2Board>;
  remove(id: string): Promise<void>;
  opsSince(id: string, since: number, limit?: number): Promise<CanvasV2OpsPage>;
  appendOps(
    id: string,
    input: CanvasV2AppendOpsInput,
  ): Promise<CanvasV2AppendOpsResult>;
}

export const CANVAS_V2_STREAM_SERVICE = Symbol.for(
  "posthog.core.canvasV2.streamService",
);

export interface ICanvasV2StreamService {
  streamBoard(
    boardId: string,
    signal?: AbortSignal,
  ): AsyncGenerator<CanvasV2StreamEvent>;
  sendPresence(boardId: string, input: CanvasV2PresenceInput): Promise<void>;
}
