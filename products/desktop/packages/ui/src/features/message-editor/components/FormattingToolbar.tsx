import {
  CodeBlockIcon,
  CodeIcon,
  ListBulletsIcon,
  ListNumbersIcon,
  QuotesIcon,
  TextBIcon,
  TextItalicIcon,
  TextStrikethroughIcon,
} from "@phosphor-icons/react";
import { Button, Separator } from "@posthog/quill";
import type { Editor } from "@tiptap/react";
import { useEditorState } from "@tiptap/react";

interface FormattingControl {
  key: string;
  label: string;
  Icon: typeof TextBIcon;
  isActive: (editor: Editor) => boolean;
  run: (editor: Editor) => void;
  /** Starts a group; renders a separator before it. */
  startsGroup?: boolean;
}

const CONTROLS: FormattingControl[] = [
  {
    key: "bold",
    label: "Bold",
    Icon: TextBIcon,
    isActive: (e) => e.isActive("bold"),
    run: (e) => e.chain().focus().toggleBold().run(),
  },
  {
    key: "italic",
    label: "Italic",
    Icon: TextItalicIcon,
    isActive: (e) => e.isActive("italic"),
    run: (e) => e.chain().focus().toggleItalic().run(),
  },
  {
    key: "strike",
    label: "Strikethrough",
    Icon: TextStrikethroughIcon,
    isActive: (e) => e.isActive("strike"),
    run: (e) => e.chain().focus().toggleStrike().run(),
  },
  {
    key: "code",
    label: "Code",
    Icon: CodeIcon,
    isActive: (e) => e.isActive("code"),
    run: (e) => e.chain().focus().toggleCode().run(),
  },
  {
    key: "codeBlock",
    label: "Code block",
    Icon: CodeBlockIcon,
    isActive: (e) => e.isActive("codeBlock"),
    run: (e) => e.chain().focus().toggleCodeBlock().run(),
  },
  {
    key: "bulletList",
    label: "Bulleted list",
    Icon: ListBulletsIcon,
    isActive: (e) => e.isActive("bulletList"),
    run: (e) => e.chain().focus().toggleBulletList().run(),
    startsGroup: true,
  },
  {
    key: "orderedList",
    label: "Numbered list",
    Icon: ListNumbersIcon,
    isActive: (e) => e.isActive("orderedList"),
    run: (e) => e.chain().focus().toggleOrderedList().run(),
  },
  {
    key: "blockquote",
    label: "Quote",
    Icon: QuotesIcon,
    isActive: (e) => e.isActive("blockquote"),
    run: (e) => e.chain().focus().toggleBlockquote().run(),
  },
];

export function FormattingToolbar({
  editor,
  disabled,
}: {
  editor: Editor | null;
  disabled?: boolean;
}) {
  const active = useEditorState({
    editor,
    selector: ({ editor: current }) =>
      current
        ? CONTROLS.map((control) => control.isActive(current)).join(",")
        : "",
  });

  if (!editor) {
    return null;
  }

  const activeFlags = (active ?? "").split(",");

  return (
    <div className="flex select-none items-center gap-0.5 px-1">
      {CONTROLS.map((control, index) => (
        <span key={control.key} className="flex items-center gap-0.5">
          {control.startsGroup && (
            <Separator orientation="vertical" className="mx-1 h-4" />
          )}
          <Button
            variant="default"
            size="icon-sm"
            aria-label={control.label}
            disabled={disabled}
            data-selected={activeFlags[index] === "true" || undefined}
            onClick={() => control.run(editor)}
            className="text-muted-foreground data-selected:bg-fill-selected data-selected:text-foreground"
          >
            <control.Icon size={14} />
          </Button>
        </span>
      ))}
    </div>
  );
}
