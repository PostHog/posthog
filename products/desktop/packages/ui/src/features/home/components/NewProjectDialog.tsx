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
} from "@posthog/quill";
import type { UserBasic } from "@posthog/shared/domain-types";
import { useHomeProjectsStore } from "@posthog/ui/features/home/homeProjectsStore";
import { type FormEvent, useEffect, useId, useState } from "react";

export interface NewProjectSpace {
  id: string;
  name: string;
}

/**
 * Create a project inside one of the pinned spaces. The space is picked here
 * and never changes afterwards: everything the project gathers is scoped by
 * that space, so moving one would change who can see its work.
 */
export function NewProjectDialog({
  open,
  onOpenChange,
  spaces,
  defaultSpaceId,
  currentUser,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  spaces: NewProjectSpace[];
  defaultSpaceId?: string;
  currentUser: UserBasic | null;
}) {
  const nameFieldId = useId();
  const spaceFieldId = useId();
  const createProject = useHomeProjectsStore((state) => state.createProject);
  const [name, setName] = useState("");
  const [spaceId, setSpaceId] = useState(defaultSpaceId ?? spaces[0]?.id ?? "");

  // Reopening should start clean, and the space list may have loaded since the
  // last time this mounted.
  useEffect(() => {
    if (!open) return;
    setName("");
    setSpaceId(defaultSpaceId ?? spaces[0]?.id ?? "");
  }, [open, defaultSpaceId, spaces]);

  const canCreate = name.trim().length > 0 && spaceId.length > 0;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!canCreate) return;
    createProject({ spaceId, name: name.trim(), lead: currentUser });
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>New project</DialogTitle>
          <DialogDescription>
            A project gathers the plans, canvases, todos and sessions for one
            piece of work.
          </DialogDescription>
        </DialogHeader>
        <form onSubmit={submit}>
          <DialogBody viewportClassName="flex flex-col gap-3">
            <Field>
              <FieldLabel htmlFor={nameFieldId}>Name</FieldLabel>
              <Input
                id={nameFieldId}
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="Onboarding revamp"
                autoFocus
              />
            </Field>
            <Field>
              <FieldLabel htmlFor={spaceFieldId}>Space</FieldLabel>
              <Select
                value={spaceId}
                onValueChange={(value) => setSpaceId(String(value))}
              >
                <SelectTrigger id={spaceFieldId}>
                  {/* The trigger shows the value it was given unless it is told
                      how to read it, and a space's value is an opaque id. */}
                  <SelectValue>
                    {(value) => {
                      const space = spaces.find((s) => s.id === value);
                      return space ? `#${space.name}` : "Pick a space";
                    }}
                  </SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {spaces.map((space) => (
                    <SelectItem key={space.id} value={space.id}>
                      #{space.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </Field>
          </DialogBody>
          <DialogFooter>
            <DialogClose render={<Button variant="outline">Cancel</Button>} />
            <Button type="submit" variant="primary" disabled={!canCreate}>
              Create project
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
