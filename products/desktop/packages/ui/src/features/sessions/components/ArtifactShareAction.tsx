import { ShareNetworkIcon } from "@phosphor-icons/react";
import {
  Button,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { fileLinkHasUnpublishedChanges } from "@posthog/ui/features/sharing/publicLink";
import { ShareModal } from "@posthog/ui/features/sharing/ShareModal";
import { useArtifactSharingQuery } from "@posthog/ui/features/sharing/useArtifactSharing";
import { useState } from "react";

/** The share button in an artifact tab's header; opens the share dialog for the displayed version. */
export function ArtifactShareAction({
  taskId,
  runId,
  artifactId,
  name,
}: {
  taskId: string;
  runId: string;
  artifactId: string;
  name: string;
}) {
  const [open, setOpen] = useState(false);
  const sharing = useArtifactSharingQuery(taskId, artifactId);
  const needsPublish = fileLinkHasUnpublishedChanges(sharing.data);

  return (
    <>
      <Tooltip>
        <TooltipTrigger
          render={
            <Button
              size="icon"
              variant="default"
              className="relative"
              aria-label={
                needsPublish
                  ? "Share…, changes ready to publish to the public link"
                  : "Share…"
              }
              data-attr="artifact-share-open"
              onClick={() => setOpen(true)}
            >
              <ShareNetworkIcon size={14} />
              {needsPublish && (
                <span
                  aria-hidden
                  className="absolute top-0.5 right-0.5 size-1.5 rounded-full bg-red-9 ring-2 ring-background"
                />
              )}
            </Button>
          }
        />
        <TooltipContent>Share this file</TooltipContent>
      </Tooltip>
      {open && (
        <ShareModal
          target={{ kind: "artifact", taskId, runId, artifactId, name }}
          surface="thread_panel"
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}
