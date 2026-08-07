import type { IconProps } from "@phosphor-icons/react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
  Text,
} from "@posthog/quill";
import type { ComponentType, ReactElement, ReactNode } from "react";

interface RightColumnSectionProps {
  Icon: ComponentType<IconProps>;
  title: string;
  rightSlot?: ReactNode;
  defaultOpen?: boolean;
  children: ReactNode;
}

/**
 * Slim caption header used by every section in the detail-view right column.
 * Smaller and lighter than `DetailSection` (no spanning divider) so the
 * side column reads as supporting detail rather than competing with the
 * main Summary on the left.
 */
export function RightColumnSection({
  Icon,
  title,
  rightSlot,
  defaultOpen = true,
  children,
}: RightColumnSectionProps): ReactElement {
  return (
    <Collapsible
      defaultOpen={defaultOpen}
      variant="folder"
      className="flex flex-col gap-2"
    >
      <div className="flex select-none items-center gap-2 text-gray-10">
        <CollapsibleTrigger className="min-w-0 flex-1 text-left">
          <Icon className="shrink-0" aria-hidden />
          <Text
            render={<span />}
            size="xxs"
            variant="muted"
            weight="medium"
            className="uppercase tracking-[0.06em]"
          >
            {title}
          </Text>
        </CollapsibleTrigger>
        {rightSlot != null && <div className="shrink-0">{rightSlot}</div>}
      </div>
      <CollapsibleContent>{children}</CollapsibleContent>
    </Collapsible>
  );
}
