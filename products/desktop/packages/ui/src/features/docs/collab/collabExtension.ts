import { Extension } from "@tiptap/core";
import { collab } from "@tiptap/pm/collab";

export interface DocCollabOptions {
  /** Server version the editor's starting content came from. */
  version: number;
  /** Unique per open editor, so a client never rebases its own steps. */
  clientId: string;
}

/**
 * prosemirror-collab as a Tiptap extension.
 *
 * Tiptap's own Collaboration extension is Yjs-based; docs sync through
 * server-authoritative steps instead, so the plugin is wrapped here directly.
 */
export const DocCollab = Extension.create<DocCollabOptions>({
  name: "docCollab",

  addOptions() {
    return { version: 0, clientId: "" };
  },

  addProseMirrorPlugins() {
    return [
      collab({
        version: this.options.version,
        clientID: this.options.clientId,
      }),
    ];
  },
});
