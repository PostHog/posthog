import { createSuggestionLoader } from "@posthog/core/message-editor/suggestionLoader";
import {
  SuggestionList,
  type SuggestionListRef,
} from "@posthog/ui/features/message-editor/tiptap/SuggestionList";
import type { SuggestionItem } from "@posthog/ui/features/message-editor/types";
import { getPortalContainer } from "@posthog/ui/primitives/ThemeWrapper";
import type { Editor, Range } from "@tiptap/core";
import { Extension } from "@tiptap/core";
import { ReactRenderer } from "@tiptap/react";
import Suggestion, { type SuggestionOptions } from "@tiptap/suggestion";
import type { ReactNode } from "react";
import tippy, { type Instance as TippyInstance } from "tippy.js";

export interface DocSuggestionConfig<T extends SuggestionItem> {
  /** Extension name; must be unique in the editor. */
  name: string;
  /** Tags the popup element so one editor's popup is distinguishable from another's. */
  sessionId: string;
  char: string;
  startOfLine?: boolean;
  allowSpaces?: boolean;
  debounceMs?: number;
  items: (query: string) => T[] | Promise<T[]>;
  renderItem?: (item: T) => ReactNode;
  /** Runs with the trigger text already deleted; insert whatever the item means. */
  onSelect: (context: { editor: Editor; item: T }) => void;
}

/**
 * A typeahead inside a doc: `@` for people, `/` for blocks.
 *
 * The message composer has its own factory that always inserts a mention chip.
 * A doc needs the same popup but different results, so this one hands the
 * selected item back instead of deciding what to insert.
 */
export function createDocSuggestion<T extends SuggestionItem>(
  config: DocSuggestionConfig<T>,
): Extension {
  const loader = createSuggestionLoader<T>({
    items: config.items,
    debounceMs: config.debounceMs ?? 0,
  });

  let renderer: ReactRenderer<SuggestionListRef> | null = null;
  let currentCommand: ((item: SuggestionItem) => void) | null = null;

  const renderItemUntyped = config.renderItem
    ? (item: SuggestionItem) => config.renderItem?.(item as T)
    : undefined;

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

  const suggestion: Omit<SuggestionOptions<T>, "editor"> = {
    char: config.char,
    allowSpaces: config.allowSpaces ?? false,
    startOfLine: config.startOfLine ?? false,

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
          renderer.element.setAttribute(
            "data-suggestion-session",
            config.sessionId,
          );

          if (!props.clientRect) return;
          const container = getPortalContainer();
          popup = tippy(container, {
            getReferenceClientRect: props.clientRect as () => DOMRect,
            appendTo: () => container,
            content: renderer.element,
            showOnCreate: true,
            interactive: true,
            trigger: "manual",
            placement: "bottom-start",
            offset: [0, 8],
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

    command: ({
      editor,
      range,
      props,
    }: {
      editor: Editor;
      range: Range;
      props: T;
    }) => {
      editor.chain().focus().deleteRange(range).run();
      config.onSelect({ editor, item: props });
    },
  };

  return Extension.create({
    name: config.name,
    addProseMirrorPlugins() {
      return [Suggestion({ editor: this.editor, ...suggestion })];
    },
  });
}
