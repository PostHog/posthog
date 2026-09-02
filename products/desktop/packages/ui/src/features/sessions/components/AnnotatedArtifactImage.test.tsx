import type { ResourceComment } from "@posthog/api-client/posthog-client";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";
import { AnnotatedArtifactImage } from "./AnnotatedArtifactImage";

vi.mock("@posthog/ui/primitives/SafeImagePreview", () => ({
  ZoomableImage: ({ overlay }: { overlay: (scale: number) => ReactNode }) =>
    overlay(1),
}));

describe("AnnotatedArtifactImage", () => {
  it("labels a deleted comment author neutrally", () => {
    const comment = {
      id: "comment-1",
      content: "Look here",
      created_by: null,
      item_context: {
        anchor: {
          kind: "region",
          x: 0.1,
          y: 0.1,
          width: 0.1,
          height: 0.1,
        },
      },
    } as unknown as ResourceComment;

    render(
      <AnnotatedArtifactImage
        src="data:image/png;base64,"
        name="example.png"
        comments={[comment]}
        activeThreadId={null}
        locateRequest={null}
        commenting={false}
        members={[]}
        onCommentingChange={vi.fn()}
        onActivateThread={vi.fn()}
        onCreate={vi.fn()}
        onError={vi.fn()}
      />,
    );

    expect(
      screen.getByLabelText("Open comment from Deleted user"),
    ).toBeInTheDocument();
  });
});
