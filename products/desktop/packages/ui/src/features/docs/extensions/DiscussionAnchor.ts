import { Mark, mergeAttributes } from "@tiptap/core";

/**
 * The phrase a discussion was started from.
 *
 * The mark carries the thread's anchor key, which is the same key the thread
 * row carries. That is what lets a click in the text open the right thread and
 * a click in the panel find the right phrase, without either side storing a
 * position that editing would invalidate.
 */
export const DiscussionAnchor = Mark.create({
  name: "discussionAnchor",
  inclusive: false,
  excludes: "",

  addAttributes() {
    return {
      anchorKey: {
        default: "",
        parseHTML: (element) => element.getAttribute("data-anchor-key") ?? "",
        renderHTML: (attributes) => ({
          "data-anchor-key": attributes.anchorKey,
        }),
      },
      resolved: {
        default: false,
        parseHTML: (element) =>
          element.getAttribute("data-resolved") === "true",
        renderHTML: (attributes) => ({
          "data-resolved": attributes.resolved ? "true" : "false",
        }),
      },
    };
  },

  parseHTML() {
    return [{ tag: "span[data-anchor-key]" }];
  },

  renderHTML({ HTMLAttributes }) {
    return [
      "span",
      mergeAttributes(HTMLAttributes, { class: "doc-discussion-anchor" }),
      0,
    ];
  },
});
