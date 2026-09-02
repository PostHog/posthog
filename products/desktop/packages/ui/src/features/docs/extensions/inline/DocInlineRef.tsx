import { cn } from "@posthog/quill";
import { NodeViewWrapper, type ReactNodeViewProps } from "@tiptap/react";
import type { ReactElement } from "react";
import { DocRefHover } from "./DocRefCard";
import type { InlineRefKind, InlineRefState } from "./types";

/**
 * The look of every inline reference: a mark, the words, and a fine underline
 * that reads as part of the sentence rather than a lozenge.
 */
export function DocRefInline({
  state,
  selected = false,
}: {
  state: InlineRefState;
  selected?: boolean;
}): ReactElement {
  const content = (
    <>
      {state.mark ? <span className="doc-ref-mark">{state.mark}</span> : null}
      {state.label}
    </>
  );
  const className = cn("doc-ref", selected && "doc-ref--selected");

  // One element for every reference, clickable or not, so the underline sits
  // at the same height in a sentence that mixes both.
  const trigger = state.onOpen ? (
    // biome-ignore lint/a11y/useSemanticElements: a button cannot flow inline and wrap with the sentence
    <span
      role="button"
      tabIndex={0}
      className={className}
      onClick={state.onOpen}
      onKeyDown={(event) => {
        if (event.key === "Enter") state.onOpen?.();
      }}
    >
      {content}
    </span>
  ) : (
    <span className={className}>{content}</span>
  );

  return <DocRefHover card={state.card} trigger={trigger} />;
}

/** The node view every kind is rendered through. */
export function DocInlineRef<A>({
  kind,
  node,
  selected,
}: { kind: InlineRefKind<A> } & ReactNodeViewProps): ReactElement {
  const attrs = node.attrs as A;
  const state = kind.useRef(attrs);

  return (
    <NodeViewWrapper
      as="span"
      className="doc-ref-host"
      {...kind.domAttributes(attrs)}
    >
      <DocRefInline state={state} selected={selected} />
    </NodeViewWrapper>
  );
}
