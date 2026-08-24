import { FolderOpenIcon, GithubLogoIcon } from "@phosphor-icons/react";
import {
  Button,
  Checkbox,
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@posthog/quill";
import { FolderPicker } from "@posthog/ui/features/folder-picker/FolderPicker";
import { RepositoriesField } from "@posthog/ui/features/integrations/components/RepositoriesField";
import { useState } from "react";

interface TaskRepositoryDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  cloud: boolean;
  repositories: string[];
  integrationId: number | null;
  folder: string;
  onApply: (selection: {
    repositories: string[];
    integrationId: number | null;
    folder: string;
    saveToSpace: boolean;
  }) => void;
}

/**
 * The task's repository (cloud) or folder (local) selection — a chip for the
 * composer's selector row, drawn like the WorkspaceModeSelect beside it.
 * Clicking it opens the TaskRepositoryDialog.
 */
export function TaskRepositoryChip({
  cloud,
  repositoryCount,
  hasFolder,
  disabled,
  onOpen,
}: {
  cloud: boolean;
  repositoryCount: number;
  hasFolder: boolean;
  disabled: boolean;
  onOpen: () => void;
}) {
  const label = cloud
    ? repositoryCount > 0
      ? `${repositoryCount} ${repositoryCount === 1 ? "repository" : "repositories"}`
      : "Add repositories…"
    : hasFolder
      ? "Folder selected"
      : "Select folder…";

  return (
    <Button
      type="button"
      variant="default"
      size="sm"
      disabled={disabled}
      aria-label={cloud ? "Task repositories" : "Task folder"}
      onClick={onOpen}
    >
      <span className="text-muted-foreground">
        {cloud ? <GithubLogoIcon size={14} /> : <FolderOpenIcon size={14} />}
      </span>
      {label}
    </Button>
  );
}

export function TaskRepositoryDialog({
  open,
  onOpenChange,
  cloud,
  repositories,
  integrationId,
  folder,
  onApply,
}: TaskRepositoryDialogProps) {
  const [draftRepositories, setDraftRepositories] = useState(repositories);
  const [draftIntegrationId, setDraftIntegrationId] = useState(integrationId);
  const [draftFolder, setDraftFolder] = useState(folder);
  const [saveToSpace, setSaveToSpace] = useState(false);

  const [wasOpen, setWasOpen] = useState(open);
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) {
      setDraftRepositories(repositories);
      setDraftIntegrationId(integrationId);
      setDraftFolder(folder);
      setSaveToSpace(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>
            {cloud ? "Add repositories" : "Select folder"}
          </DialogTitle>
          <DialogDescription>
            {cloud
              ? "Choose the repositories this task can work across."
              : "Choose the local folder this task should work in."}
          </DialogDescription>
        </DialogHeader>
        <DialogBody>
          {cloud ? (
            <div className="flex flex-col gap-4">
              <RepositoriesField
                selected={draftRepositories}
                integrationId={draftIntegrationId}
                onChange={(next, nextIntegrationId) => {
                  setDraftRepositories(next);
                  setDraftIntegrationId(nextIntegrationId);
                }}
              />
              <label
                htmlFor="save-task-repositories-to-space"
                className="flex cursor-pointer items-center gap-2 text-sm"
              >
                <Checkbox
                  id="save-task-repositories-to-space"
                  checked={saveToSpace}
                  onCheckedChange={(checked) =>
                    setSaveToSpace(checked === true)
                  }
                />
                Use these repositories for the whole space
              </label>
            </div>
          ) : (
            <FolderPicker
              value={draftFolder}
              onChange={setDraftFolder}
              placeholder="Select folder…"
              variant="field"
            />
          )}
        </DialogBody>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant="primary"
            disabled={!cloud && !draftFolder}
            onClick={() => {
              onApply({
                repositories: draftRepositories,
                integrationId: draftIntegrationId,
                folder: draftFolder,
                saveToSpace,
              });
              onOpenChange(false);
            }}
          >
            {cloud ? (
              <GithubLogoIcon size={16} />
            ) : (
              <FolderOpenIcon size={16} />
            )}
            Apply
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
