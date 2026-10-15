import { ArchiveIcon } from "@phosphor-icons/react";
import {
  formatHotkey,
  SHORTCUTS,
} from "@posthog/ui/features/command/keyboard-shortcuts";
import type { ComponentType, ReactElement, ReactNode } from "react";

export interface TaskArchiveMenuParts {
  Item: ComponentType<{
    children: ReactNode;
    disabled?: boolean;
    variant?: "default" | "destructive";
    onClick?: () => void;
  }>;
  Shortcut: ComponentType<{ children: ReactNode }>;
}

export function TaskArchiveMenuItem({
  parts,
  onClick,
}: {
  parts: TaskArchiveMenuParts;
  onClick: () => void;
}): ReactElement {
  const { Item, Shortcut } = parts;

  return (
    <Item onClick={onClick}>
      <ArchiveIcon size={14} />
      Archive
      <Shortcut>{formatHotkey(SHORTCUTS.ARCHIVE_TASK)}</Shortcut>
    </Item>
  );
}
