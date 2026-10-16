import { cn } from "@posthog/quill";
import { useDialogFocus } from "@posthog/ui/features/settings/components/useDialogFocus";
import { type ReactNode, useRef } from "react";
import { createPortal } from "react-dom";
import { useHotkeys } from "react-hotkeys-hook";

/**
 * Portaled into `#portal-container` rather than a quill `Dialog`, which
 * portals to `body`: settings pages still use Radix Themes, whose styles only
 * apply inside the `<Theme>` root that container sits in.
 */
export function SettingsDialogFrame({
  onDismiss,
  onEscape = onDismiss,
  seeThrough = false,
  children,
}: {
  onDismiss: () => void;
  onEscape?: () => void;
  seeThrough?: boolean;
  children: ReactNode;
}) {
  useHotkeys("escape", onEscape, {
    enableOnContentEditable: true,
    enableOnFormTags: true,
    preventDefault: true,
  });

  const dialogRef = useRef<HTMLDivElement>(null);
  const trapTab = useDialogFocus(dialogRef);

  const container =
    document.getElementById("portal-container") ?? document.body;
  return createPortal(
    <div
      className="absolute inset-0 z-[100] flex items-center justify-center p-12"
      data-overlay="settings"
    >
      <div
        aria-hidden
        className={cn(
          "absolute inset-0 transition-colors duration-200",
          seeThrough ? "bg-transparent" : "bg-blackA-8 dark:bg-blackA-10",
        )}
        onClick={onDismiss}
      />
      <div
        ref={dialogRef}
        role="dialog"
        tabIndex={-1}
        onKeyDown={trapTab}
        aria-modal="true"
        aria-label="Settings"
        className="relative flex h-[min(760px,100%)] w-[min(1080px,100%)] flex-col overflow-hidden rounded-lg border border-border bg-background shadow-2xl outline-none"
      >
        {children}
      </div>
    </div>,
    container,
  );
}
