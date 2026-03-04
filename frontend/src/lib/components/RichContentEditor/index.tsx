import "./RichContentEditor.scss";

import { EditorContent, Extensions, useEditor } from "@tiptap/react";
import { BindLogic } from "kea";
import { PropsWithChildren, useEffect } from "react";

import { cn } from "lib/utils/css-classes";

import { richContentEditorLogic } from "./richContentEditorLogic";
import { JSONContent, TTEditor } from "./types";

type RichContentEditorProps = {
  initialContent?: JSONContent;
  onCreate?: (editor: TTEditor) => void;
  onUpdate?: (content: JSONContent) => void;
  onSelectionUpdate?: () => void;
  extensions: Extensions;
  disabled?: boolean;
  autoFocus?: boolean;
};

export const RichContentEditor = ({
  logicKey,
  className,
  children,
  disabled = false,
  autoFocus = false,
  ...editorProps
}: PropsWithChildren<
  {
    logicKey: string;
    className?: string;
    autoFocus?: boolean;
  } & RichContentEditorProps
>): JSX.Element => {
  const editor = useRichContentEditor(editorProps);

  useEffect(() => {
    if (editor) {
      editor.setOptions({ editable: !disabled });
    }
  }, [editor, disabled]);

  return (
    <EditorContent
      editor={editor}
      className={cn("RichContentEditor", className)}
      autoFocus={autoFocus}
      spellCheck={editor?.isFocused}
    >
      {editor && (
        <BindLogic logic={richContentEditorLogic} props={{ logicKey, editor }}>
          {children}
        </BindLogic>
      )}
    </EditorContent>
  );
};

export const useRichContentEditor = ({
  extensions,
  disabled,
  initialContent,
  onCreate = () => {},
  onUpdate = () => {},
  onSelectionUpdate = () => {},
}: RichContentEditorProps): TTEditor => {
  const editor = useEditor({
    shouldRerenderOnTransaction: false,
    extensions,
    editable: !disabled,
    content: initialContent,

    editorProps: {
      handlePaste(view, event) {
        const text = event.clipboardData?.getData("text/plain");

        if (!text) {
          return false;
        }

        const looksLikeMarkdown = /(^|\n)#\s|```|\n[-*]\s|(^|\n)>\s/.test(text);

        if (!looksLikeMarkdown) {
          return false;
        }

        event.preventDefault();

        view.dispatch(view.state.tr.insertText(text));

        return true;
      },
    },
    onSelectionUpdate: onSelectionUpdate,
    onUpdate: ({ editor }) => onUpdate(editor.getJSON()),
    onCreate: ({ editor }) => onCreate(editor),
  });

  useEffect(() => {
    if (editor) {
      editor.setOptions({ editable: !disabled });
    }
  }, [editor, disabled]);

  if (!editor) {
    return editor as unknown as TTEditor;
  }

  return editor;
};
