import { Button } from "@posthog/quill";
import type { ReactNode } from "react";

/**
 * One actionable entry in a space's menu, rendered the same whether it surfaces
 * in the hover "..." dropdown, the right-click context menu, or the space's
 * hover card.
 */
export type ChannelActionItem = {
  key: string;
  label: string;
  icon: ReactNode;
  onSelect: () => void;
  variant?: "destructive";
  disabled?: boolean;
  /** Draw a divider above this item to separate it from the previous group. */
  separatorBefore?: boolean;
};

/**
 * The same actions as a plain list, for a surface that is already open — the
 * space's hover card. Buttons rather than menu items for the reason the session
 * card's list uses them: there is no menu root here to give a menu item its
 * keyboard handling.
 *
 * `onAction` closes the card once something has been chosen. The separators the
 * menus draw are dropped: the card's own rules already divide it, and a third
 * rule inside a four-item list is more chrome than grouping.
 */
export function ChannelActionList({
  actions,
  onAction,
}: {
  actions: ChannelActionItem[];
  onAction: () => void;
}) {
  return (
    <div className="flex flex-col">
      {actions.map((action) => (
        <Button
          key={action.key}
          variant={action.variant === "destructive" ? "destructive" : "default"}
          size="default"
          left
          disabled={action.disabled}
          className="w-full"
          onClick={() => {
            action.onSelect();
            onAction();
          }}
        >
          {action.icon}
          {action.label}
        </Button>
      ))}
    </div>
  );
}
