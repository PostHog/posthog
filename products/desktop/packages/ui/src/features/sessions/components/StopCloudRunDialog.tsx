import { StopCircle } from "@phosphor-icons/react";
import {
  SESSION_SERVICE,
  type SessionService,
} from "@posthog/core/sessions/sessionService";
import { useService } from "@posthog/di/react";
import { GitDialog } from "@posthog/ui/features/git-interaction/components/GitInteractionDialogs";
import { Text } from "@radix-ui/themes";
import { useState } from "react";

interface StopCloudRunDialogProps {
  open: boolean;
  taskId: string;
  runId?: string;
  title: string;
  buttonLabel: string;
  onOpenChange: (open: boolean) => void;
  onStopped?: () => void;
}

export function StopCloudRunDialog({
  open,
  taskId,
  runId,
  title,
  buttonLabel,
  onOpenChange,
  onStopped,
}: StopCloudRunDialogProps) {
  const sessionService = useService<SessionService>(SESSION_SERVICE);
  const [isStopping, setIsStopping] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleOpenChange = (nextOpen: boolean) => {
    if (!nextOpen) {
      setError(null);
    }
    onOpenChange(nextOpen);
  };

  const handleConfirm = async () => {
    setIsStopping(true);
    setError(null);
    try {
      const stopped = await sessionService.stopCloudRun(taskId, runId);
      if (!stopped) {
        setError("Couldn't stop the run. Try again in a moment.");
        return;
      }
      onStopped?.();
      handleOpenChange(false);
    } finally {
      setIsStopping(false);
    }
  };

  return (
    <GitDialog
      open={open}
      onOpenChange={handleOpenChange}
      icon={<StopCircle size={14} />}
      title={title}
      error={error}
      buttonLabel={buttonLabel}
      isSubmitting={isStopping}
      onSubmit={handleConfirm}
    >
      <Text color="gray" className="text-[13px]">
        This ends the cloud session and shuts down its sandbox. You can pick the
        conversation back up later by sending a new message. To stop only the
        current response, press Esc instead.
      </Text>
    </GitDialog>
  );
}
