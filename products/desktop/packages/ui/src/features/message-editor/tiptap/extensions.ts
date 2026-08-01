import Placeholder from "@tiptap/extension-placeholder";
import StarterKit from "@tiptap/starter-kit";
import { createCommandMention } from "./CommandMention";
import { createFileMention } from "./FileMention";
import { createIssueMention } from "./IssueMention";
import { MentionChipNode } from "./MentionChipNode";

export interface EditorExtensionsOptions {
  sessionId: string;
  placeholder?: string;
  fileMentions?: boolean;
  issueMentions?: boolean;
  commands?: boolean;
}

export function getEditorExtensions(options: EditorExtensionsOptions) {
  const {
    sessionId,
    placeholder = "",
    fileMentions = true,
    issueMentions = true,
    commands = true,
  } = options;

  const extensions = [
    StarterKit.configure({
      heading: false,
      blockquote: false,
      codeBlock: false,
      bulletList: false,
      orderedList: false,
      listItem: false,
      horizontalRule: false,
      bold: false,
      italic: false,
      strike: false,
      code: false,
    }),
    Placeholder.configure({ placeholder }),
    MentionChipNode,
  ];

  if (fileMentions) {
    extensions.push(createFileMention(sessionId));
  }

  if (issueMentions) {
    extensions.push(createIssueMention(sessionId));
  }

  if (commands) {
    extensions.push(createCommandMention({ sessionId }));
  }

  return extensions;
}
