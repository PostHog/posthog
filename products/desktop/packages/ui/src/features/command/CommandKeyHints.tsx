import { Kbd, KbdGroup } from "@posthog/quill";
import { formatHotkeyParts } from "@posthog/ui/features/command/keyboard-shortcuts";
import type { ReactNode } from "react";

export function CommandKeyHints({
  newTabHint = false,
  children,
}: {
  /** Whether the highlighted row has a place of its own to open. */
  newTabHint?: boolean;
  children?: ReactNode;
}) {
  return (
    <div className="flex items-center justify-center gap-4 border-border border-t py-1">
      <div className="flex items-center gap-2">
        <KbdGroup>
          <Kbd>↑</Kbd>
          <Kbd>↓</Kbd>
        </KbdGroup>
        <span className="text-xs">navigate</span>
      </div>
      <div className="flex items-center gap-2">
        <KbdGroup>
          <Kbd>↵</Kbd>
        </KbdGroup>
        <span className="text-xs">select</span>
      </div>
      {newTabHint && (
        <div className="flex items-center gap-2">
          <KbdGroup>
            <Kbd>{formatHotkeyParts("mod+enter").join("")}</Kbd>
          </KbdGroup>
          <span className="text-xs">new tab</span>
        </div>
      )}
      <div className="flex items-center gap-2">
        <KbdGroup>
          <Kbd>Esc</Kbd>
        </KbdGroup>
        <span className="text-xs">close</span>
      </div>
      {children}
    </div>
  );
}
