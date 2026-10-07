import { PlusIcon } from "@phosphor-icons/react";
import { Button } from "@posthog/quill";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";

export function NewLoopButton({
  label,
  limitReason,
  onClick,
}: {
  label: string;
  limitReason: string | null;
  onClick: () => void;
}) {
  const button = (
    <Button
      type="button"
      variant="primary"
      size="sm"
      onClick={onClick}
      disabled={limitReason != null}
    >
      <PlusIcon size={14} />
      {label}
    </Button>
  );
  return limitReason ? (
    <Tooltip content={limitReason}>
      <span className="inline-flex">{button}</span>
    </Tooltip>
  ) : (
    button
  );
}
