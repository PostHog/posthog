import { XIcon } from "@phosphor-icons/react";
import { Button } from "@posthog/quill";
import type { ReactElement, ReactNode } from "react";

interface BoardPanelProps {
  title: string;
  closeLabel: string;
  onClose?: () => void;
  /** Buttons that sit left of the close button, such as "New session". */
  actions?: ReactNode;
  children: ReactNode;
}

/** The shell every side panel shares, so all four line up with the board. */
export function BoardPanel({
  title,
  closeLabel,
  onClose,
  actions,
  children,
}: BoardPanelProps): ReactElement {
  return (
    <div className="@container flex h-full min-h-0 w-full flex-col overflow-hidden border-(--gray-4) border-l">
      <header className="flex h-12 shrink-0 items-center justify-between gap-2 border-(--gray-4) border-b pr-2 pl-3">
        <h2 className="min-w-0 truncate font-semibold text-[13px] tracking-tight">
          {title}
        </h2>
        <div className="flex shrink-0 items-center gap-1">
          {actions}
          {onClose ? (
            <Button
              variant="default"
              size="icon-sm"
              aria-label={closeLabel}
              onClick={onClose}
            >
              <XIcon />
            </Button>
          ) : null}
        </div>
      </header>
      {children}
    </div>
  );
}
