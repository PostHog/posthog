import Placeholder from "@tiptap/extension-placeholder";
import StarterKit from "@tiptap/starter-kit";
import { BlockShortcuts } from "./blockShortcuts";
import { createCommandMention } from "./CommandMention";
import { createFileMention } from "./FileMention";
import { createIssueMention } from "./IssueMention";
import { MentionChipNode } from "./MentionChipNode";
import { MarkdownLineStartRules } from "./markdownInputRules";

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
      horizontalRule: false,
      bold: false,
      italic: false,
      strike: false,
    }),
    Placeholder.configure({ placeholder }),
    BlockShortcuts,
    MarkdownLineStartRules,
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
