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
import { useEffect, useState } from "react";
import { RepositoriesField } from "./RepositoriesField";

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

  useEffect(() => {
    if (!open) return;
    setDraftRepositories(repositories);
    setDraftIntegrationId(integrationId);
    setDraftFolder(folder);
    setSaveToSpace(false);
  }, [open, repositories, integrationId, folder]);

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
            disabled={cloud ? draftRepositories.length === 0 : !draftFolder}
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
