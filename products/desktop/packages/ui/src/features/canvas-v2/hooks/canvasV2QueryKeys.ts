/**
 * Query keys for the board data that does not come from a tRPC query hook:
 * the sync client's op pages and the folded board state. tRPC procedures keep
 * their own keys; these keep the hand-rolled caches under one namespace.
 */
export const canvasV2QueryKeys = {
  all: ["canvas-v2"] as const,
  boards: () => [...canvasV2QueryKeys.all, "boards"] as const,
  board: (boardId: string) =>
    [...canvasV2QueryKeys.all, "board", boardId] as const,
  ops: (boardId: string) => [...canvasV2QueryKeys.all, "ops", boardId] as const,
};
