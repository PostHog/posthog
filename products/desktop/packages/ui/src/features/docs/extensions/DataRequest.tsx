import { DocMark } from "@posthog/ui/primitives/DocMark";
import { mergeAttributes, Node } from "@tiptap/core";
import {
  NodeViewWrapper,
  type ReactNodeViewProps,
  ReactNodeViewRenderer,
} from "@tiptap/react";
import { useEffect, useState } from "react";
import { DocRefHover } from "./inline/DocRefCard";

/**
 * A data point the sentence has asked for and does not have yet.
 *
 * It sits in the line where the figure will sit, in the reader's own words,
 * while the agent writes the query behind it. A block would break the sentence
 * in two and leave a hole in the page. A click opens its thread.
 */

export type DataRequestState = "asking" | "reply" | "answered" | "failed";

export interface DataRequestAttrs {
  requestId: string;
  question: string;
  taskId: string | null;
  state: DataRequestState;
  /** When the request was made, so a long wait can say so. */
  askedAt: number | null;
}

const STATE_TITLE: Record<DataRequestState, string> = {
  asking: "The agent is looking for this.",
  reply: "The agent wrote in the thread.",
  answered: "The agent answered in the thread.",
  failed: "The agent did not find this.",
};

/** Said beside the words, so a line never looks stalled. */
const STATE_NOTE: Partial<Record<DataRequestState, string>> = {
  reply: "see thread",
  answered: "see thread",
  failed: "not found",
};

const SLOW_AFTER_MS = 20_000;

export function DataRequestView({ node }: ReactNodeViewProps) {
  const { question, state, askedAt, requestId } =
    node.attrs as DataRequestAttrs;
  const [slow, setSlow] = useState(false);

  useEffect(() => {
    if (state !== "asking" || !askedAt) return;
    const left = SLOW_AFTER_MS - (Date.now() - askedAt);
    if (left <= 0) {
      setSlow(true);
      return;
    }
    const timer = setTimeout(() => setSlow(true), left);
    return () => clearTimeout(timer);
  }, [state, askedAt]);

  const note =
    STATE_NOTE[state] ?? (slow && state === "asking" ? "still looking" : null);
  const markState =
    state === "asking" ? "working" : state === "failed" ? "failed" : "still";

  return (
    <NodeViewWrapper as="span" className="inline" data-request-id={requestId}>
      <DocRefHover
        card={{
          title: question,
          meta: (
            <>
              {STATE_TITLE[state] ?? STATE_TITLE.asking} Click to open the
              thread.
            </>
          ),
        }}
        trigger={
          <span className="doc-datarequest" data-state={state}>
            <DocMark
              variant="agent"
              state={markState}
              size={11}
              className="doc-datarequest-mark"
            />
            {question}
            {note ? <span className="doc-datarequest-note">{note}</span> : null}
          </span>
        }
      />
    </NodeViewWrapper>
  );
}

export const DataRequest = Node.create({
  name: "dataRequest",
  group: "inline",
  inline: true,
  atom: true,
  selectable: true,

  addAttributes() {
    return {
      requestId: { default: "" },
      question: { default: "" },
      taskId: { default: null },
      state: { default: "asking" },
      askedAt: { default: null },
    };
  },

  parseHTML() {
    return [{ tag: "span[data-data-request]" }];
  },

  renderHTML({ HTMLAttributes }) {
    return [
      "span",
      mergeAttributes(HTMLAttributes, { "data-data-request": "" }),
      HTMLAttributes.question ?? "",
    ];
  },

  addNodeView() {
    return ReactNodeViewRenderer(DataRequestView);
  },
});
