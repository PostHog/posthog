import { Extension } from "@tiptap/core";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";

export interface RemoteCaret {
  clientId: string;
  userName: string;
  anchor: number;
  head: number;
  /** Milliseconds since the epoch; a caret older than the timeout is dropped. */
  seenAt: number;
}

export const remoteCaretsKey = new PluginKey<DecorationSet>("docRemoteCarets");

/** A caret nobody has refreshed for this long is treated as gone. */
export const REMOTE_CARET_TIMEOUT_MS = 30_000;

/** Six stable colors, picked by client id so a person keeps one color per session. */
const CARET_COLORS = [
  "var(--blue-9)",
  "var(--grass-9)",
  "var(--purple-9)",
  "var(--tomato-9)",
  "var(--amber-9)",
  "var(--cyan-9)",
];

export function caretColor(clientId: string): string {
  let hash = 0;
  for (const character of clientId) {
    hash = (hash * 31 + character.charCodeAt(0)) % 997;
  }
  return CARET_COLORS[hash % CARET_COLORS.length];
}

/**
 * Draws other people's carets and selections.
 *
 * The set is replaced wholesale on every ping through a transaction meta, so a
 * dropped ping self-heals on the next one and nothing has to be reconciled.
 */
export const RemoteCarets = Extension.create({
  name: "docRemoteCarets",

  addProseMirrorPlugins() {
    return [
      new Plugin<DecorationSet>({
        key: remoteCaretsKey,
        state: {
          init: () => DecorationSet.empty,
          apply(transaction, current, _oldState, newState) {
            const carets = transaction.getMeta(remoteCaretsKey) as
              | RemoteCaret[]
              | undefined;
            if (!carets)
              return current.map(transaction.mapping, transaction.doc);
            return DecorationSet.create(
              newState.doc,
              buildDecorations(carets, newState.doc.content.size),
            );
          },
        },
        props: {
          decorations(state) {
            return remoteCaretsKey.getState(state) ?? DecorationSet.empty;
          },
        },
      }),
    ];
  },
});

function buildDecorations(
  carets: RemoteCaret[],
  docSize: number,
): Decoration[] {
  const decorations: Decoration[] = [];

  for (const caret of carets) {
    const anchor = clamp(caret.anchor, docSize);
    const head = clamp(caret.head, docSize);
    const color = caretColor(caret.clientId);

    if (anchor !== head) {
      decorations.push(
        Decoration.inline(Math.min(anchor, head), Math.max(anchor, head), {
          class: "doc-remote-selection",
          style: `background-color: color-mix(in srgb, ${color} 22%, transparent);`,
        }),
      );
    }

    decorations.push(
      Decoration.widget(
        head,
        () => caretElement(caret.clientId, caret.userName, color),
        {
          side: 10,
          key: `caret-${caret.clientId}-${head}`,
        },
      ),
    );
  }

  return decorations;
}

function caretElement(
  clientId: string,
  userName: string,
  color: string,
): HTMLElement {
  const wrapper = document.createElement("span");
  wrapper.className = "doc-remote-caret";
  wrapper.style.borderColor = color;
  // The header's faces scroll to a caret by this attribute.
  wrapper.dataset.caretClient = clientId;

  const label = document.createElement("span");
  label.className = "doc-remote-caret-label";
  label.style.backgroundColor = color;
  label.textContent = userName;
  wrapper.appendChild(label);

  return wrapper;
}

function clamp(position: number, docSize: number): number {
  if (!Number.isFinite(position)) return 0;
  return Math.max(0, Math.min(position, docSize));
}
