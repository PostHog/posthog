import { Extension } from "@tiptap/core";
import type { EditorState, Transaction } from "@tiptap/pm/state";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";
import { getCommandSuggestions } from "../suggestions/getSuggestions";
import type { CommandSuggestionItem } from "../types";

interface GhostMatch {
  slashPos: number;
  cursorPos: number;
  query: string;
  item: CommandSuggestionItem;
}

interface PluginState {
  ghost: GhostMatch | null;
  dismissedAt: number | null;
}

type GhostMeta = { type: "dismiss" } | { type: "reset" };

const pluginKey = new PluginKey<PluginState>("commandGhostText");
const SLASH_QUERY_REGEX = /(?:^|\s)\/([^\s/]+)$/;

const getGhost = (state: EditorState): GhostMatch | null =>
  pluginKey.getState(state)?.ghost ?? null;

function computeGhost(
  sessionId: string,
  state: EditorState,
): GhostMatch | null {
  if (!sessionId) return null;
  const { selection } = state;
  if (!selection.empty) return null;

  const $from = selection.$from;
  const textBeforeCursor = $from.parent.textBetween(
    0,
    $from.parentOffset,
    "\n",
    "\uFFFC",
  );

  const match = SLASH_QUERY_REGEX.exec(textBeforeCursor);
  if (!match) return null;

  const query = match[1];
  const slashPos =
    $from.start() + match.index + (match[0].length - query.length - 1);

  if (state.doc.resolve(slashPos).parentOffset === 0) return null;

  const top = getCommandSuggestions(sessionId, query)[0];
  if (!top) return null;

  const lowerLabel = top.label.toLowerCase();
  const lowerQuery = query.toLowerCase();
  if (!lowerLabel.startsWith(lowerQuery) || lowerLabel === lowerQuery) {
    return null;
  }

  return { slashPos, cursorPos: selection.from, query, item: top };
}

function createGhostWidget(text: string): HTMLElement {
  const span = document.createElement("span");
  span.textContent = text;
  span.className = "cli-command-ghost pointer-events-none text-[var(--gray-9)]";
  return span;
}

function acceptGhost(
  state: EditorState,
  dispatch: (tr: Transaction) => void,
): boolean {
  const ghost = getGhost(state);
  if (!ghost) return false;

  const chipType = state.schema.nodes.mentionChip;
  if (!chipType) return false;

  const chip = chipType.create({
    type: "command",
    id: ghost.item.id,
    label: ghost.item.label,
    pastedText: false,
    skillPath: ghost.item.skillPath,
    skillSource: ghost.item.skillSource,
    skillName: ghost.item.skillName,
  });
  const space = state.schema.text(" ");

  dispatch(
    state.tr
      .replaceWith(ghost.slashPos, ghost.cursorPos, [chip, space])
      .setMeta(pluginKey, { type: "reset" } satisfies GhostMeta),
  );
  return true;
}

export function createCommandGhostText(sessionId: string) {
  return Extension.create({
    name: "commandGhostText",

    addProseMirrorPlugins() {
      return [
        new Plugin<PluginState>({
          key: pluginKey,
          state: {
            init: () => ({ ghost: null, dismissedAt: null }),
            apply: (tr, prev, _old, next) => {
              const meta = tr.getMeta(pluginKey) as GhostMeta | undefined;

              if (meta?.type === "reset") {
                return { ghost: null, dismissedAt: null };
              }

              const ghost = computeGhost(sessionId, next);

              if (meta?.type === "dismiss") {
                return { ghost: null, dismissedAt: ghost?.slashPos ?? null };
              }

              const suppressed =
                prev.dismissedAt !== null &&
                ghost?.slashPos === prev.dismissedAt;

              if (suppressed) {
                return { ghost: null, dismissedAt: prev.dismissedAt };
              }

              return { ghost, dismissedAt: null };
            },
          },
          props: {
            decorations(state) {
              const ghost = getGhost(state);
              if (!ghost) return null;

              const remainder = ghost.item.label.slice(ghost.query.length);
              if (!remainder) return null;

              return DecorationSet.create(state.doc, [
                Decoration.widget(
                  ghost.cursorPos,
                  createGhostWidget(remainder),
                  {
                    side: 1,
                    key: "command-ghost",
                  },
                ),
              ]);
            },
            handleKeyDown(view, event) {
              if (!getGhost(view.state)) return false;

              if (event.key === "Tab") {
                event.preventDefault();
                return acceptGhost(view.state, view.dispatch);
              }

              if (event.key === "Escape") {
                event.preventDefault();
                view.dispatch(
                  view.state.tr.setMeta(pluginKey, {
                    type: "dismiss",
                  } satisfies GhostMeta),
                );
                return true;
              }

              return false;
            },
          },
        }),
      ];
    },
  });
}
