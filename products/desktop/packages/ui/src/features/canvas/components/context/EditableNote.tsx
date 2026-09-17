import { PencilSimpleIcon } from "@phosphor-icons/react";
import { type KeyboardEvent, useState } from "react";

interface EditableNoteProps {
  prefix: string | null;
  note: string;
  onSave: (note: string) => Promise<void>;
  disabled: boolean;
}

export function EditableNote({
  prefix,
  note,
  onSave,
  disabled,
}: EditableNoteProps) {
  const [draft, setDraft] = useState<string | null>(null);

  const commit = async () => {
    if (draft === null) return;
    const next = draft.trim();
    setDraft(null);
    if (next !== note) await onSave(next);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      event.preventDefault();
      void commit();
    }
    if (event.key === "Escape") {
      event.preventDefault();
      setDraft(null);
    }
  };

  if (draft !== null) {
    return (
      <input
        ref={(element) => element?.focus()}
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={() => void commit()}
        onKeyDown={onKeyDown}
        placeholder="What this is, in a few words"
        aria-label="Description"
        className="w-full bg-transparent text-muted-foreground text-xs outline-none placeholder:text-muted-foreground/60"
      />
    );
  }

  const summary = [prefix, note].filter(Boolean).join(" · ");
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => setDraft(note)}
      aria-label={note ? "Edit description" : "Add a description"}
      className="flex min-w-0 items-center gap-1 text-left text-muted-foreground text-xs"
    >
      {summary ? <span className="truncate">{summary}</span> : null}
      {note ? (
        <PencilSimpleIcon
          size={11}
          className="shrink-0 opacity-0 transition-opacity group-hover/row:opacity-100"
        />
      ) : (
        <span className="shrink-0 opacity-0 transition-opacity group-hover/row:opacity-100">
          {summary ? "· " : ""}Add a description
        </span>
      )}
    </button>
  );
}
