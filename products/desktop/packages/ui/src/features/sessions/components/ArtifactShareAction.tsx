import { ShareNetworkIcon } from "@phosphor-icons/react";
import {
  Button,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import { ShareModal } from "@posthog/ui/features/sharing/ShareModal";
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

  return (
    <>
      <Tooltip>
        <TooltipTrigger
          render={
            <Button
              size="icon"
              variant="default"
              aria-label="Share…"
              data-attr="artifact-share-open"
              onClick={() => setOpen(true)}
            >
              <ShareNetworkIcon size={14} />
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
