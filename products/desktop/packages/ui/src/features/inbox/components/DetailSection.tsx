import type { IconProps } from "@phosphor-icons/react";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
  Text,
} from "@posthog/quill";
import type { ComponentType, ReactElement, ReactNode } from "react";

interface DetailSectionProps {
  Icon: ComponentType<IconProps>;
  title: string;
  rightSlot?: ReactNode;
  defaultOpen?: boolean;
  children: ReactNode;
}

export function DetailSection({
  Icon,
  title,
  rightSlot,
  defaultOpen = true,
  children,
}: DetailSectionProps): ReactElement {
  return (
    <Collapsible
      defaultOpen={defaultOpen}
      variant="folder"
      className="flex flex-col gap-3"
    >
      <div className="flex min-w-0 select-none items-center gap-3">
        <CollapsibleTrigger className="min-w-0 flex-1 text-left">
          <Icon weight="bold" aria-hidden />
          <Text
            render={<span />}
            size="sm"
            weight="semibold"
            className="truncate tracking-[-0.01em]"
          >
            {title}
          </Text>
          <div className="h-px min-w-4 flex-1 bg-(--gray-5)" />
        </CollapsibleTrigger>
        {rightSlot != null && <div className="shrink-0">{rightSlot}</div>}
      </div>
      <CollapsibleContent>{children}</CollapsibleContent>
    </Collapsible>
  );
}
