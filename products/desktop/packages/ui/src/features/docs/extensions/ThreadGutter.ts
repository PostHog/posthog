import { Extension } from "@tiptap/core";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";

/**
 * A paragraph that has an agent thread, marked in the right margin.
 *
 * The thread is not part of the sentence, so it does not belong in it. The
 * block carries the task id and a class; the mark itself is drawn in the margin
 * by `DocThreadGutter`, which measures against the column instead of the line.
 */
export const THREAD_ATTRIBUTE = "threadTaskId";

export const threadGutterKey = new PluginKey("docThreadGutter");

/** Blocks that can own a thread. A list item's paragraph counts through its parent. */
const THREAD_BLOCKS = ["paragraph", "heading"];

export const ThreadGutter = Extension.create({
  name: "docThreadGutter",

  addGlobalAttributes() {
    return [
      {
        types: THREAD_BLOCKS,
        attributes: {
          [THREAD_ATTRIBUTE]: {
            default: null,
            parseHTML: (element) => element.getAttribute("data-thread-task"),
            renderHTML: (attributes) =>
              attributes[THREAD_ATTRIBUTE]
                ? { "data-thread-task": attributes[THREAD_ATTRIBUTE] }
                : {},
          },
        },
      },
    ];
  },

  addProseMirrorPlugins() {
    return [
      new Plugin({
        key: threadGutterKey,
        props: {
          decorations(state) {
            const decorations: Decoration[] = [];
            state.doc.descendants((node, pos) => {
              const taskId = node.attrs?.[THREAD_ATTRIBUTE];
              if (!taskId || !THREAD_BLOCKS.includes(node.type.name)) return;
              decorations.push(
                Decoration.node(pos, pos + node.nodeSize, {
                  class: "doc-has-thread",
                }),
              );
            });
            return DecorationSet.create(state.doc, decorations);
          },
        },
      }),
    ];
  },
});
