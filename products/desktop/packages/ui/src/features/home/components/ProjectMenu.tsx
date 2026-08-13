import { DotsThreeIcon } from "@phosphor-icons/react";
import {
  AlertDialog,
  AlertDialogClose,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
  Dialog,
  DialogBody,
  DialogClose,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  Field,
  FieldLabel,
  Input,
} from "@posthog/quill";
import { useHomeProjectsStore } from "@posthog/ui/features/home/homeProjectsStore";
import { type FormEvent, useEffect, useId, useState } from "react";

/**
 * Rename or remove a project, from the heading its work sits under. Both live
 * here rather than in the toolbar because a project is only ever named on the
 * table once, and that is where the reader is already looking at it.
 */
export function ProjectMenu({
  projectId,
  projectName,
}: {
  projectId: string;
  projectName: string;
}) {
  const nameFieldId = useId();
  const renameProject = useHomeProjectsStore((state) => state.renameProject);
  const deleteProject = useHomeProjectsStore((state) => state.deleteProject);
  const [renaming, setRenaming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [name, setName] = useState(projectName);

  useEffect(() => {
    if (renaming) setName(projectName);
  }, [renaming, projectName]);

  const submitRename = (event: FormEvent) => {
    event.preventDefault();
    if (!name.trim()) return;
    renameProject(projectId, name);
    setRenaming(false);
  };

  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              variant="default"
              size="icon-sm"
              aria-label={`Actions for ${projectName}`}
            >
              <DotsThreeIcon size={16} />
            </Button>
          }
        />
        <DropdownMenuContent align="end">
          <DropdownMenuItem onClick={() => setRenaming(true)}>
            Rename…
          </DropdownMenuItem>
          <DropdownMenuItem onClick={() => setDeleting(true)}>
            Delete project…
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <Dialog open={renaming} onOpenChange={setRenaming}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Rename project</DialogTitle>
          </DialogHeader>
          <form onSubmit={submitRename}>
            <DialogBody>
              <Field>
                <FieldLabel htmlFor={nameFieldId}>Name</FieldLabel>
                <Input
                  id={nameFieldId}
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  autoFocus
                />
              </Field>
            </DialogBody>
            <DialogFooter>
              <DialogClose render={<Button variant="outline">Cancel</Button>} />
              <Button type="submit" variant="primary" disabled={!name.trim()}>
                Save
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <AlertDialog open={deleting} onOpenChange={setDeleting}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete {projectName}?</AlertDialogTitle>
            <AlertDialogDescription>
              The plans and todos in this project go with it. Sessions and
              canvases stay where they are, and lose their project.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogClose
              render={<Button variant="outline">Cancel</Button>}
            />
            <Button
              variant="destructive"
              onClick={() => {
                deleteProject(projectId);
                setDeleting(false);
              }}
            >
              Delete project
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );
}
