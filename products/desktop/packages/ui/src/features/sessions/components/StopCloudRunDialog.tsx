import { StopCircle } from "@phosphor-icons/react";
import {
  SESSION_SERVICE,
  type SessionService,
} from "@posthog/core/sessions/sessionService";
import { useService } from "@posthog/di/react";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
  Text,
} from "@posthog/quill";
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
    <AlertDialog open={open} onOpenChange={() => undefined}>
      <AlertDialogContent
        className="max-w-[400px]"
        onKeyDown={(event) => {
          if (event.key === "Escape") event.preventDefault();
        }}
      >
        <AlertDialogHeader>
          <AlertDialogTitle>
            <span className="flex items-center gap-2">
              <StopCircle size={14} />
              {title}
            </span>
          </AlertDialogTitle>
          <AlertDialogDescription>
            This ends the cloud session and shuts down its sandbox. You can pick
            the conversation back up later by sending a new message. To stop
            only the current response, press Esc instead.
          </AlertDialogDescription>
        </AlertDialogHeader>
        {error && (
          <Text size="sm" variant="destructive" role="alert">
            {error}
          </Text>
        )}
        <AlertDialogFooter>
          <Button
            variant="outline"
            disabled={isStopping}
            onClick={() => handleOpenChange(false)}
          >
            Cancel
          </Button>
          <Button
            variant="destructive-outline"
            loading={isStopping}
            disabled={isStopping}
            onClick={() => void handleConfirm()}
          >
            {buttonLabel}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
