import { Spinner, StopCircle } from "@phosphor-icons/react";
import { isTerminalStatus } from "@posthog/core/cloud-task/schemas";
import { Button as QuillButton } from "@posthog/quill";
import { useState } from "react";
import { shallow } from "zustand/shallow";
import { useSessionSelector } from "../useSession";
import { StopCloudRunDialog } from "./StopCloudRunDialog";

interface StopCloudRunButtonProps {
  taskId: string;
}

export function StopCloudRunButton({ taskId }: StopCloudRunButtonProps) {
  const { isCloud, cloudStatus, stopRequested } = useSessionSelector(
    taskId,
    (session) => ({
      isCloud: session?.isCloud ?? false,
      cloudStatus: session?.cloudStatus ?? null,
      stopRequested: session?.stopRequested ?? false,
    }),
    shallow,
  );
  const [confirmOpen, setConfirmOpen] = useState(false);

  if (!isCloud || isTerminalStatus(cloudStatus)) return null;

  return (
    <>
      <div className="no-drag flex items-center">
        <QuillButton
          variant="outline"
          size="sm"
          disabled={stopRequested}
          onClick={() => setConfirmOpen(true)}
        >
          {stopRequested ? (
            <Spinner size={14} className="shrink-0 animate-spin" />
          ) : (
            <StopCircle size={14} weight="regular" className="shrink-0" />
          )}
          {stopRequested ? "Stopping..." : "Stop run"}
        </QuillButton>
      </div>
      <StopCloudRunDialog
        open={confirmOpen}
        taskId={taskId}
        title="Stop run"
        buttonLabel="Stop run"
        onOpenChange={setConfirmOpen}
      />
    </>
  );
}
