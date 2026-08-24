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
  /** Rich text marks and blocks. Off by default: an agent prompt is plain text. */
  formatting?: boolean;
}

export function getEditorExtensions(options: EditorExtensionsOptions) {
  const {
    sessionId,
    placeholder = "",
    fileMentions = true,
    issueMentions = true,
    commands = true,
    formatting = false,
  } = options;

  const extensions = [
    StarterKit.configure(
      formatting
        ? { heading: false, horizontalRule: false }
        : {
            heading: false,
            blockquote: false,
            horizontalRule: false,
            bold: false,
            italic: false,
            strike: false,
          },
    ),
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
