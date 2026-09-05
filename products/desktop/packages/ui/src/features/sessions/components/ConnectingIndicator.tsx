import { Text } from "@posthog/quill";
import type { TaskRunStatus } from "@posthog/shared/domain-types";
import { Spinner } from "@posthog/ui/primitives/Spinner";

interface ConnectingIndicatorProps {
  isCloud?: boolean;
  cloudStatus?: TaskRunStatus | null;
  queued?: boolean;
}

function label(
  isCloud: boolean,
  cloudStatus: TaskRunStatus | null | undefined,
): string {
  if (!isCloud) {
    return "Connecting to agent";
  }
  switch (cloudStatus) {
    case "queued":
      return "Waiting in the queue";
    case "in_progress":
      return "Starting the sandbox";
    default:
      return "Connecting to agent";
  }
}

export function ConnectingIndicator({
  isCloud = false,
  cloudStatus,
  queued = false,
}: ConnectingIndicatorProps) {
  const text = queued
    ? "Your message will send once the agent connects"
    : label(isCloud, cloudStatus);

  return (
    <div className="flex select-none items-center gap-2 px-1 py-1">
      <Spinner size={12} className="shrink-0 text-(--gray-9)" />
      <Text render={<span />} className="truncate text-(--gray-11) text-[13px]">
        {text}
      </Text>
    </div>
  );
}
