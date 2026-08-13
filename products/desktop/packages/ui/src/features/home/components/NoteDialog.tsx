import type { HomeNote, HomeStatus } from "@posthog/core/home/schemas";
import {
  HOME_STATUS_LABELS,
  HOME_STATUS_ORDER,
} from "@posthog/core/home/schemas";
import {
  Button,
  Dialog,
  DialogBody,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Field,
  FieldLabel,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
} from "@posthog/quill";
import type { UserBasic } from "@posthog/shared/domain-types";
import { HomeStatusIcon } from "@posthog/ui/features/home/components/HomeStatusIcon";
import { useHomeProjectsStore } from "@posthog/ui/features/home/homeProjectsStore";
import { type FormEvent, useEffect, useId, useState } from "react";

export interface NoteDialogProject {
  id: string;
  name: string;
  spaceName: string;
}

/**
 * What the dialog is doing this time: writing a new plan or todo into a
 * project, or opening one that already exists.
 */
export type NoteDialogTarget =
  | { mode: "create"; kind: HomeNote["kind"]; projectId?: string }
  | { mode: "edit"; noteId: string };

const KIND_COPY: Record<HomeNote["kind"], { title: string; hint: string }> = {
  plan: {
    title: "New plan",
    hint: "Write out the approach before anyone starts building.",
  },
  todo: {
    title: "New todo",
    hint: "One thing that needs doing, in a sentence.",
  },
};

/**
 * The editor for the two kinds of work this app owns outright. Everything else
 * on the home table opens somewhere it already lives, so this is the only place
 * a row's own contents can be written.
 */
export function NoteDialog({
  target,
  onClose,
  projects,
  currentUser,
}: {
  /** Null while nothing is open, which is also what closes the dialog. */
  target: NoteDialogTarget | null;
  onClose: () => void;
  projects: NoteDialogProject[];
  currentUser: UserBasic | null;
}) {
  const titleFieldId = useId();
  const statusFieldId = useId();
  const projectFieldId = useId();
  const bodyFieldId = useId();
  const notes = useHomeProjectsStore((state) => state.notes);
  const createNote = useHomeProjectsStore((state) => state.createNote);
  const updateNote = useHomeProjectsStore((state) => state.updateNote);
  const deleteNote = useHomeProjectsStore((state) => state.deleteNote);

  const existing =
    target?.mode === "edit" ? (notes[target.noteId] ?? null) : null;
  const kind =
    existing?.kind ?? (target?.mode === "create" ? target.kind : "todo");
  // Asked to open something that is no longer there: deleted in another window,
  // or dropped by a schema change. Staying shut is the honest answer; falling
  // through would offer a create form nobody asked for.
  const open = target?.mode === "create" || existing != null;

  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [status, setStatus] = useState<HomeStatus>("todo");
  const [projectId, setProjectId] = useState("");

  // Load the dialog's fields from whatever it was opened on, once per opening.
  // The note is read off the store imperatively rather than from the subscribed
  // copy, so saving does not hand this effect a new record and reset the form
  // out from under whoever is still typing.
  useEffect(() => {
    if (!target) return;
    if (target.mode === "edit") {
      const note = useHomeProjectsStore.getState().notes[target.noteId];
      setTitle(note?.title ?? "");
      setBody(note?.body ?? "");
      setStatus(note?.status ?? "todo");
      setProjectId(note?.projectId ?? "");
      return;
    }
    setTitle("");
    setBody("");
    setStatus("todo");
    setProjectId(target.projectId ?? projects[0]?.id ?? "");
  }, [target, projects]);

  const canSave = title.trim().length > 0 && projectId.length > 0;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!canSave) return;
    if (existing) {
      updateNote(existing.id, { title: title.trim(), body, status });
    } else {
      createNote({
        projectId,
        kind,
        title: title.trim(),
        body,
        assignee: currentUser,
      });
    }
    onClose();
  };

  const remove = () => {
    if (existing) deleteNote(existing.id);
    onClose();
  };

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>
            {existing ? title || "Untitled" : KIND_COPY[kind].title}
          </DialogTitle>
          {existing ? null : (
            <DialogDescription>{KIND_COPY[kind].hint}</DialogDescription>
          )}
        </DialogHeader>
        <form onSubmit={submit}>
          <DialogBody viewportClassName="flex flex-col gap-3">
            <Field>
              <FieldLabel htmlFor={titleFieldId}>Title</FieldLabel>
              <Input
                id={titleFieldId}
                value={title}
                onChange={(event) => setTitle(event.target.value)}
                placeholder={
                  kind === "plan" ? "Rework the setup flow" : "Update the docs"
                }
                autoFocus
              />
            </Field>

            {existing ? (
              <Field>
                <FieldLabel htmlFor={statusFieldId}>Status</FieldLabel>
                <Select
                  value={status}
                  onValueChange={(value) => setStatus(value as HomeStatus)}
                >
                  <SelectTrigger id={statusFieldId}>
                    <SelectValue>
                      {(value) => HOME_STATUS_LABELS[value as HomeStatus]}
                    </SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {HOME_STATUS_ORDER.map((option) => (
                      <SelectItem key={option} value={option}>
                        <HomeStatusIcon status={option} size={14} />
                        {HOME_STATUS_LABELS[option]}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
            ) : (
              <Field>
                <FieldLabel htmlFor={projectFieldId}>Project</FieldLabel>
                <Select
                  value={projectId}
                  onValueChange={(value) => setProjectId(String(value))}
                >
                  <SelectTrigger id={projectFieldId}>
                    <SelectValue>
                      {(value) =>
                        projects.find((project) => project.id === value)
                          ?.name ?? "Pick a project"
                      }
                    </SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {projects.map((project) => (
                      <SelectItem key={project.id} value={project.id}>
                        {project.name}
                        <span className="text-muted-foreground">
                          #{project.spaceName}
                        </span>
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
            )}

            <Field>
              <FieldLabel htmlFor={bodyFieldId}>
                {kind === "plan" ? "Plan" : "Notes"}
              </FieldLabel>
              <Textarea
                id={bodyFieldId}
                value={body}
                onChange={(event) => setBody(event.target.value)}
                rows={kind === "plan" ? 10 : 4}
                placeholder="Markdown"
              />
            </Field>
          </DialogBody>
          <DialogFooter>
            {existing ? (
              <Button variant="outline" type="button" onClick={remove}>
                Delete
              </Button>
            ) : null}
            <DialogClose render={<Button variant="outline">Cancel</Button>} />
            <Button type="submit" variant="primary" disabled={!canSave}>
              {existing ? "Save" : "Create"}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
