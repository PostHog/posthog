import type { SelectionCommentOverlay } from "@posthog/ui/features/code-editor/components/SelectionCommentOverlay";
import type { ArtifactHtmlFrameProps } from "@posthog/ui/features/sessions/components/artifactHtmlFrameHost";
import { act, render } from "@testing-library/react";
import type { ComponentProps } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  frameProps: null as ArtifactHtmlFrameProps | null,
  overlayProps: null as ComponentProps<typeof SelectionCommentOverlay> | null,
}));

vi.mock("./artifactHtmlFrame", () => ({
  ArtifactHtmlFrame: (props: ArtifactHtmlFrameProps) => {
    mocks.frameProps = props;
    return null;
  },
}));
vi.mock(
  "@posthog/ui/features/code-editor/components/SelectionCommentOverlay",
  () => ({
    SelectionCommentOverlay: (
      props: ComponentProps<typeof SelectionCommentOverlay>,
    ) => {
      mocks.overlayProps = props;
      return null;
    },
  }),
);

import { AnnotatedArtifactHtml } from "./AnnotatedArtifactHtml";

const frameRect = {
  top: 100,
  left: 200,
  right: 600,
  bottom: 500,
  width: 400,
  height: 400,
};

function selectionMessage(channel: unknown): Record<string, unknown> {
  return {
    marker: "__POSTHOG_ARTIFACT_COMMENT_BRIDGE__",
    channel,
    type: "selection",
    anchor: {
      kind: "text",
      quote: "selected text",
      prefix: "",
      suffix: "",
      start: 0,
      end: 13,
    },
    rect: {
      top: 10,
      left: 10,
      right: 30,
      bottom: 20,
      width: 20,
      height: 10,
    },
  };
}

describe("AnnotatedArtifactHtml", () => {
  beforeEach(() => {
    mocks.frameProps = null;
    mocks.overlayProps = null;
  });

  it("keeps the comment composer attached to its selection while scrolling", () => {
    render(
      <AnnotatedArtifactHtml
        html="<p>selected text</p>"
        name="report.html"
        commentsEnabled
        comments={[]}
        activeThreadId={null}
        locateRequest={null}
        members={[]}
        onActivateThread={vi.fn()}
        onCreate={vi.fn()}
        onResolutionsChange={vi.fn()}
      />,
    );
    const channel = mocks.frameProps?.messages[0]?.channel;

    act(() => {
      mocks.frameProps?.onMessage(selectionMessage(channel), frameRect);
    });
    expect(mocks.overlayProps?.selection?.anchor).toEqual({
      top: 110,
      endX: 230,
      bottom: 120,
    });

    act(() => {
      mocks.frameProps?.onMessage(
        {
          marker: "__POSTHOG_ARTIFACT_COMMENT_BRIDGE__",
          channel,
          type: "selection-position",
          rect: {
            top: -20,
            left: 10,
            right: 30,
            bottom: -10,
            width: 20,
            height: 10,
          },
        },
        frameRect,
      );
    });
    expect(mocks.overlayProps?.selection?.anchor).toEqual({
      top: 80,
      endX: 230,
      bottom: 90,
    });
  });
});
