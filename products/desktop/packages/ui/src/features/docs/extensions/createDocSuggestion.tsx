import { createSuggestionLoader } from "@posthog/core/message-editor/suggestionLoader";
import type { SuggestionItem } from "@posthog/ui/features/message-editor/types";
import { getPortalContainer } from "@posthog/ui/primitives/ThemeWrapper";
import type { Editor, Range } from "@tiptap/core";
import { Extension } from "@tiptap/core";
import { PluginKey } from "@tiptap/pm/state";
import { ReactRenderer } from "@tiptap/react";
import Suggestion, { type SuggestionOptions } from "@tiptap/suggestion";
import tippy, { type Instance as TippyInstance } from "tippy.js";
import {
  DocSuggestionList,
  type DocSuggestionListRef,
} from "./DocSuggestionList";

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
  /** Said when nothing matches what was typed. */
  emptyMessage?: string;
  /** Runs with the trigger text already deleted; insert whatever the item means. */
  onSelect: (context: { editor: Editor; item: T }) => void;
}

/**
 * A typeahead inside a doc: `@` for people, `/` for blocks, `+` for data.
 *
 * The message composer has its own factory that always inserts a mention chip.
 * A doc needs its own popup and different results, so this one hands the
 * selected item back instead of deciding what to insert.
 */
export function createDocSuggestion<T extends SuggestionItem>(
  config: DocSuggestionConfig<T>,
): Extension {
  const loader = createSuggestionLoader<T>({
    items: config.items,
    debounceMs: config.debounceMs ?? 0,
  });

  let renderer: ReactRenderer<DocSuggestionListRef> | null = null;
  let currentCommand: ((item: SuggestionItem) => void) | null = null;

  const pushProps = () => {
    if (!renderer || !currentCommand) return;
    const { items, loading } = loader.getState();
    renderer.updateProps({
      items,
      command: currentCommand,
      loading,
      emptyMessage: config.emptyMessage,
    });
  };

  loader.subscribe(() => pushProps());

  // Every suggestion plugin needs its own key. The default one is shared, so a
  // second typeahead in the same editor is rejected outright by ProseMirror.
  const pluginKey = new PluginKey(`docSuggestion-${config.name}`);

  const suggestion: Omit<SuggestionOptions<T>, "editor"> = {
    pluginKey,
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
          renderer = new ReactRenderer(DocSuggestionList, {
            props: {
              items,
              command: props.command,
              loading,
              emptyMessage: config.emptyMessage,
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
