import type {
  CanvasV2AppendOpsInput,
  CanvasV2AppendOpsResult,
  CanvasV2Board,
  CanvasV2BoardSummary,
  CanvasV2OpsPage,
} from "@posthog/shared";

export const CANVAS_V2_BOARDS_SERVICE = Symbol.for(
  "posthog.core.canvasV2.boardsService",
);

export interface ICanvasV2BoardsService {
  list(): Promise<CanvasV2BoardSummary[]>;
  get(id: string): Promise<CanvasV2Board>;
  create(name: string): Promise<CanvasV2Board>;
  rename(id: string, name: string): Promise<CanvasV2Board>;
  remove(id: string): Promise<void>;
  opsSince(id: string, since: number, limit?: number): Promise<CanvasV2OpsPage>;
  appendOps(
    id: string,
    input: CanvasV2AppendOpsInput,
  ): Promise<CanvasV2AppendOpsResult>;
}
