import type { CanvasV2BoardSummary } from "@posthog/shared";
import { boardAsCanvas } from "@posthog/ui/features/canvas-v2/hooks/useBoardsAsCanvases";
import { describe, expect, it } from "vitest";

function summary(
  over: Partial<CanvasV2BoardSummary> = {},
): CanvasV2BoardSummary {
  return {
    id: "board-1",
    name: "Status board",
    channelId: "space-1",
    createdAt: "2026-09-01T10:00:00Z",
    updatedAt: "2026-09-02T10:00:00Z",
    fragmentCount: 0,
    headSeq: 0,
    pinned: false,
    preview: [],
    ...over,
  };
}

describe("boardAsCanvas", () => {
  it("carries the creator, so a row names a person in place of Unknown", () => {
    const record = boardAsCanvas(
      summary({
        createdBy: {
          kind: "user",
          userId: 7,
          userUuid: "creator-uuid",
          userName: "Ada",
          userEmail: "ada@example.com",
        },
      }),
    );

    expect(record.createdBy).toBe("Ada");
    expect(record.createdByUuid).toBe("creator-uuid");
    expect(record.createdByEmail).toBe("ada@example.com");
  });

  it("carries the person who last touched the board, for the row face", () => {
    const record = boardAsCanvas(
      summary({
        lastActor: {
          kind: "user",
          userId: 9,
          userUuid: "actor-uuid",
          userName: "Grace",
          userEmail: "grace@example.com",
        },
      }),
    );

    expect(record.lastActor).toEqual({
      name: "Grace",
      uuid: "actor-uuid",
      email: "grace@example.com",
    });
  });
});
