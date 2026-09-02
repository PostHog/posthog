import { offset, type VirtualElement } from "@floating-ui/dom";
import { DotsSixVerticalIcon, PlusIcon } from "@phosphor-icons/react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { DragHandle } from "@tiptap/extension-drag-handle-react";
import type { Node as ProseMirrorNode } from "@tiptap/pm/model";
import { PluginKey, TextSelection } from "@tiptap/pm/state";
import type { Editor } from "@tiptap/react";
import { useCallback, useMemo, useRef, useState } from "react";

interface Target {
  node: ProseMirrorNode;
  pos: number;
}

/** The handle stands in the left strip the doc column reserves for it. */
const POSITION = {
  placement: "left-start" as const,
  middleware: [offset({ mainAxis: 6, crossAxis: 3 })],
};

/**
 * The controls in the doc's left margin, on the line the pointer is on.
 *
 * The plus opens the block menu rather than inserting a plain paragraph: what a
 * person wants at that spot is a block, and naming it costs the same keystroke
 * either way. The handle drags the line, and carries what can be done to it.
 */
export function DocBlockGutter({ editor }: { editor: Editor | null }) {
  const [target, setTarget] = useState<Target | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const menuOpenRef = useRef(false);
  const targetDomRef = useRef<HTMLElement | null>(null);
  // One key per mount. A shared key makes ProseMirror refuse the second
  // instance when a rebuilt editor and the old one overlap for a frame.
  const pluginKey = useMemo(() => new PluginKey("docDragHandle"), []);

  const onNodeChange = useCallback(
    ({
      node,
      pos,
      editor: current,
    }: {
      node: ProseMirrorNode | null;
      pos: number;
      editor: Editor;
    }) => {
      if (node && pos >= 0) {
        const dom = current.view.nodeDOM(pos);
        targetDomRef.current = dom instanceof HTMLElement ? dom : null;
        setTarget({ node, pos });
        return;
      }
      // An open menu keeps the line it was opened on, whatever the pointer does.
      if (!menuOpenRef.current) setTarget(null);
    },
    [],
  );

  // A nested block sits inside its container's padding: a list item behind its
  // marker, a paragraph behind a quote's border. A handle at the block's own
  // edge lands on that. The top-level block's edge keeps every handle in the
  // margin, in one column.
  const getReferencedVirtualElement = useCallback((): VirtualElement | null => {
    const dom = targetDomRef.current;
    const root = dom?.closest(".ProseMirror");
    if (!dom || !root) return null;
    let block: HTMLElement = dom;
    while (block.parentElement && block.parentElement !== root) {
      block = block.parentElement;
    }
    if (block === dom) return null;
    return {
      contextElement: dom,
      getBoundingClientRect: () => {
        const rect = dom.getBoundingClientRect();
        const left = block.getBoundingClientRect().left;
        return new DOMRect(left, rect.top, rect.right - left, rect.height);
      },
    };
  }, []);

  const onMenuOpenChange = useCallback((open: boolean) => {
    menuOpenRef.current = open;
    setMenuOpen(open);
  }, []);

  if (!editor) return null;

  const addBlockBelow = () => {
    if (!target) return;
    const after = target.pos + target.node.nodeSize;
    const chain = editor.chain().focus();

    // A split gives the sibling the line already is: another bullet under a
    // bullet, a paragraph under a paragraph. A node with no text to split
    // takes a fresh paragraph instead.
    const endOfNode = TextSelection.near(
      editor.state.doc.resolve(after - 1),
      -1,
    ).$head.pos;
    if (endOfNode > target.pos) {
      chain.setTextSelection(endOfNode).splitBlock();
    } else {
      chain.insertContentAt(after, { type: "paragraph" });
      chain.setTextSelection(after + 1);
    }
    chain.insertContent("/").run();
  };

  const duplicateBlock = () => {
    if (!target) return;
    editor
      .chain()
      .focus()
      .insertContentAt(target.pos + target.node.nodeSize, target.node.toJSON())
      .run();
  };

  const deleteBlock = () => {
    if (!target) return;
    editor
      .chain()
      .focus()
      .deleteRange({
        from: target.pos,
        to: target.pos + target.node.nodeSize,
      })
      .run();
  };

  return (
    <DragHandle
      editor={editor}
      pluginKey={pluginKey}
      nested
      computePositionConfig={POSITION}
      getReferencedVirtualElement={getReferencedVirtualElement}
      onNodeChange={onNodeChange}
      className={
        menuOpen ? "doc-drag-handle doc-drag-handle-open" : "doc-drag-handle"
      }
    >
      <Tooltip>
        <TooltipTrigger
          render={
            <button
              type="button"
              aria-label="Add a block below this line"
              onClick={addBlockBelow}
              className="grid size-5 cursor-pointer place-items-center rounded-(--radius-2) text-(--gray-8) transition-colors hover:bg-(--gray-4) hover:text-(--gray-12)"
            />
          }
        >
          <PlusIcon size={13} />
        </TooltipTrigger>
        <TooltipContent>Add a block</TooltipContent>
      </Tooltip>
      <DropdownMenu open={menuOpen} onOpenChange={onMenuOpenChange}>
        <DropdownMenuTrigger
          // The press has to reach the drag: the menu opens on mousedown by
          // default, which ends the gesture before a drag can start.
          onMouseDown={(event) => event.preventBaseUIHandler()}
          onClick={() => onMenuOpenChange(true)}
          render={
            <button
              type="button"
              aria-label="Drag this line, or open its actions"
              className="grid size-5 cursor-grab place-items-center rounded-(--radius-2) text-(--gray-8) transition-colors hover:bg-(--gray-4) hover:text-(--gray-12) active:cursor-grabbing"
            />
          }
        >
          <DotsSixVerticalIcon size={13} />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start">
          <DropdownMenuItem onClick={duplicateBlock}>
            Duplicate
          </DropdownMenuItem>
          <DropdownMenuItem onClick={deleteBlock}>Delete</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </DragHandle>
  );
}
