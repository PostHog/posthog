import { PlusIcon } from "@phosphor-icons/react";
import { Button } from "@posthog/quill";

export function NewLoopButton({
  label,
  onClick,
}: {
  label: string;
  onClick: () => void;
}) {
  return (
    <Button type="button" variant="primary" size="sm" onClick={onClick}>
      <PlusIcon size={14} />
      {label}
    </Button>
  );
}
