import {
  Button,
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@posthog/quill";
import {
  isImageBuildFailed,
  type SandboxCustomImage,
} from "@posthog/shared/domain-types";
import { BuildLogPane } from "@posthog/ui/features/settings/sections/environments/BuildLogPane";
import { imageFailureDetail } from "@posthog/ui/features/settings/sections/environments/imageBuildWatcher";
import { EnvironmentSetupFlow } from "@posthog/ui/features/settings/sections/environments/setup/EnvironmentSetupFlow";
import { useSandboxCustomImageDetail } from "@posthog/ui/features/settings/sections/environments/useSandboxCustomImages";
import { useState } from "react";

interface CustomImageBuildDialogProps {
  /** Preselected repository, so the recommendation lands on a filled form. */
  defaultRepository: string | null;
  onClose: () => void;
}

/**
 * Building an image from the recommendation, start to finish, without leaving
 * Cost management: the same setup flow the environments page uses, and then
 * the build it started.
 */
export function CustomImageBuildDialog({
  defaultRepository,
  onClose,
}: CustomImageBuildDialogProps) {
  const [building, setBuilding] = useState<SandboxCustomImage | null>(null);

  return (
    <Dialog
      open
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
    >
      <DialogContent className="max-w-[640px]">
        {building ? (
          <BuildProgress image={building} onClose={onClose} />
        ) : (
          <>
            <DialogHeader>
              <DialogTitle>Build a custom sandbox image</DialogTitle>
              <DialogDescription>
                Cloud runs start from your dependencies and tools already
                installed instead of installing them each run.
              </DialogDescription>
            </DialogHeader>
            <DialogBody>
              <EnvironmentSetupFlow
                scope="image"
                embedded
                defaultRepository={defaultRepository}
                onDone={(image) => {
                  if (image) setBuilding(image);
                  else onClose();
                }}
              />
            </DialogBody>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

/** The build the flow just started, followed to its end. */
function BuildProgress({
  image,
  onClose,
}: {
  image: SandboxCustomImage;
  onClose: () => void;
}) {
  const { data } = useSandboxCustomImageDetail(image.id);
  const current = data ?? image;

  return (
    <>
      <DialogHeader>
        <DialogTitle>{current.name}</DialogTitle>
        <DialogDescription>{buildStatusLine(current)}</DialogDescription>
      </DialogHeader>
      <DialogBody>
        <BuildLogPane image={current} />
      </DialogBody>
      <DialogFooter>
        <Button
          variant="outline"
          size="sm"
          data-attr="cost-management-close-image-build"
          onClick={onClose}
        >
          Close
        </Button>
      </DialogFooter>
    </>
  );
}

function buildStatusLine(image: SandboxCustomImage): string {
  if (image.status === "ready") {
    return "Ready. Pick it as the base image of a cloud environment to start runs from it.";
  }
  if (isImageBuildFailed(image.status)) {
    return imageFailureDetail(image);
  }
  return "It scans first, then builds. Closing this doesn't stop the build.";
}
