import { createSuggestionLoader } from "@posthog/core/message-editor/suggestionLoader";
import type { Editor } from "@tiptap/core";
import Mention, { type MentionOptions } from "@tiptap/extension-mention";
import { ReactRenderer } from "@tiptap/react";
import type { SuggestionOptions } from "@tiptap/suggestion";
import type { ReactNode } from "react";
import tippy, { type Instance as TippyInstance } from "tippy.js";
import { getPortalContainer } from "../../../primitives/ThemeWrapper";
import type { SuggestionItem } from "../types";
import type { ChipType, MentionChipAttrs } from "./MentionChipNode";
import { SuggestionList, type SuggestionListRef } from "./SuggestionList";

export interface SuggestionMentionConfig<T extends SuggestionItem> {
  name: string;
  /** Tags the popup so keydown checks can tell this editor's popup apart. */
  sessionId: string;
  char: string;
  chipType: ChipType;
  startOfLine?: boolean;
  allowSpaces?: boolean;
  debounceMs?: number;
  items: (query: string) => T[] | Promise<T[]>;
  renderItem?: (item: T) => ReactNode;
  /**
   * When true, commit the suggestion as soon as the typed query exactly matches
   * an item's label and no other item label extends it.
   */
  autoCommit?: boolean;
  /** Override the chip attrs inserted for a given item. */
  resolveChipAttrs?: (item: T) => Partial<MentionChipAttrs>;
  /** Fires after the chip is inserted into the document. */
  onAfterInsert?: (item: T, ctx: { editor: Editor; chipId: string }) => void;
}

export function createSuggestionMention<T extends SuggestionItem>(
  config: SuggestionMentionConfig<T>,
) {
  const {
    name,
    sessionId,
    char,
    chipType,
    startOfLine = false,
    allowSpaces = false,
    debounceMs = 0,
    items: loadItems,
    renderItem,
    autoCommit = false,
    resolveChipAttrs,
    onAfterInsert,
  } = config;

  const renderItemUntyped = renderItem
    ? (item: SuggestionItem) => renderItem(item as T)
    : undefined;

  const loader = createSuggestionLoader<T>({
    items: loadItems,
    debounceMs,
  });

  let renderer: ReactRenderer<SuggestionListRef> | null = null;
  let currentCommand: ((item: SuggestionItem) => void) | null = null;

  const pushProps = () => {
    if (!renderer || !currentCommand) return;
    const { items, loading } = loader.getState();
    renderer.updateProps({
      items,
      command: currentCommand,
      renderItem: renderItemUntyped,
      loading,
    });
  };

  loader.subscribe(() => pushProps());

  const suggestion: Partial<SuggestionOptions<T>> = {
    char,
    allowSpaces,
    startOfLine,

    items: ({ query }) => loader.load(query),

    render: () => {
      let popup: TippyInstance | null = null;
      let dismissed = false;

      return {
        onStart: (props) => {
          dismissed = false;
          currentCommand = props.command;
          const { items, loading } = loader.getState();
          renderer = new ReactRenderer(SuggestionList, {
            props: {
              items,
              command: props.command,
              renderItem: renderItemUntyped,
              loading,
            },
            editor: props.editor,
          });
          renderer.element.setAttribute("data-suggestion-session", sessionId);

          if (!props.clientRect) return;

          const container = getPortalContainer();
          popup = tippy(container, {
            getReferenceClientRect: props.clientRect as () => DOMRect,
            appendTo: () => container,
            content: renderer.element,
            showOnCreate: true,
            interactive: true,
            trigger: "manual",
            placement: "top-start",
            offset: [0, 12],
            duration: 0,
          });
        },

        onUpdate: (props) => {
          if (props.items.length > 0) dismissed = false;
          currentCommand = props.command;
          pushProps();

          if (props.clientRect && popup) {
            popup.setProps({
              getReferenceClientRect: props.clientRect as () => DOMRect,
            });
          }

          if (autoCommit) {
            // Caveat: if one item label is a strict prefix of another (e.g.
            // "add" vs "add-dir"), the shorter name becomes uncommittable via
            // auto-commit and the user has to pick from the list. Avoid
            // shipping prefix-clashing command names, or rename to disambiguate.
            const q = props.query.toLowerCase();
            const exact = props.items.find((i) => i.label.toLowerCase() === q);
            const hasLongerExtension = props.items.some(
              (i) =>
                i.label.toLowerCase().startsWith(q) &&
                i.label.length > q.length,
            );
            if (exact && !hasLongerExtension) {
              props.command(exact);
            }
          }
        },

        onKeyDown: (props) => {
          if (props.event.key === "Escape") {
            props.event.stopPropagation();
            popup?.hide();
            dismissed = true;
            return true;
          }

          if (dismissed) return false;

          return renderer?.ref?.onKeyDown(props) ?? false;
        },

        onExit: () => {
          popup?.destroy();
          renderer?.destroy();
          renderer = null;
          currentCommand = null;
          loader.reset();
        },
      };
    },

    command: ({ editor, range, props }) => {
      const item = props as T;
      const chipId = crypto.randomUUID();
      const overrides = resolveChipAttrs?.(item) ?? {};
      const attrs: MentionChipAttrs = {
        type: overrides.type ?? item.chipType ?? chipType,
        id: overrides.id ?? item.id,
        label: overrides.label ?? item.label,
        pastedText: false,
        chipId,
        skillPath: overrides.skillPath ?? item.skillPath,
        skillSource: overrides.skillSource ?? item.skillSource,
        skillName: overrides.skillName ?? item.skillName,
      };
      editor
        .chain()
        .focus()
        .deleteRange(range)
        .insertContent([
          { type: "mentionChip", attrs },
          { type: "text", text: " " },
        ])
        .run();
      onAfterInsert?.(item, { editor, chipId });
    },
  };

  return Mention.extend({
    name,
    addOptions(): MentionOptions {
      const parent = this.parent?.();
      if (!parent) {
        throw new Error(`${name}: expected Mention parent options`);
      }
      return { ...parent, suggestion };
    },
  });
}
