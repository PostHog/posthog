import { TagIcon } from "@phosphor-icons/react";
import {
  Avatar,
  AvatarFallback,
  AvatarGroup,
  cn,
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@posthog/quill";
import {
  type PrototypeTag,
  type PrototypeTaskStatus,
  personById,
  STATUS_META,
} from "@posthog/ui/features/prototypes/tags/mockData";
import { NestedButton } from "@posthog/ui/primitives/NestedButton";

export function StatusDot({
  status,
  size = 8,
}: {
  status: PrototypeTaskStatus;
  size?: number;
}) {
  const meta = STATUS_META[status];
  return (
    <span
      className={cn(
        "inline-block shrink-0 rounded-full",
        meta.pulse && "animate-pulse",
      )}
      style={{
        width: size,
        height: size,
        background: meta.filled ? meta.tone : "transparent",
        boxShadow: meta.filled ? undefined : `inset 0 0 0 1.5px ${meta.tone}`,
      }}
      title={meta.label}
    />
  );
}

export function TagChip({
  tag,
  onClick,
  onRemove,
  size = "sm",
}: {
  tag: PrototypeTag;
  onClick?: () => void;
  onRemove?: () => void;
  size?: "sm" | "md";
}) {
  const className = cn(
    "inline-flex items-center gap-1 rounded-full border border-border bg-gray-2 text-gray-11",
    size === "sm" ? "px-1.5 py-px text-[11px]" : "px-2 py-0.5 text-[12px]",
    onClick && "cursor-pointer transition-colors hover:bg-gray-3",
  );
  const body = (
    <>
      <span
        className="inline-block h-1.5 w-1.5 rounded-full"
        style={{ background: `var(--${tag.hue}-9)` }}
      />
      {tag.name}
      {onRemove && (
        <NestedButton
          onActivate={onRemove}
          className="ml-0.5 rounded-full text-gray-9 hover:text-gray-12"
          aria-label={`Remove ${tag.name}`}
        >
          ×
        </NestedButton>
      )}
    </>
  );
  if (onClick) {
    // Chips can sit inside a task row that is itself a <button>.
    return (
      <NestedButton onActivate={onClick} className={className}>
        {body}
      </NestedButton>
    );
  }
  return <span className={className}>{body}</span>;
}

export function TagGlyph({
  tag,
  size = 16,
}: {
  tag: PrototypeTag;
  size?: number;
}) {
  return (
    <span
      className="flex shrink-0 items-center justify-center rounded"
      style={{
        width: size + 6,
        height: size + 6,
        background: `var(--${tag.hue}-4)`,
        color: `var(--${tag.hue}-11)`,
      }}
    >
      <TagIcon size={size - 4} weight="bold" />
    </span>
  );
}

export function FaceStack({
  personIds,
  online,
  max = 3,
}: {
  personIds: string[];
  online?: string[];
  max?: number;
}) {
  const shown = personIds.slice(0, max);
  const extra = personIds.length - shown.length;
  return (
    <AvatarGroup stacked reverse size="xs" className="shrink-0">
      {extra > 0 && (
        <Avatar size="xs">
          <AvatarFallback className="bg-gray-4 text-[9px] text-gray-11">
            +{extra}
          </AvatarFallback>
        </Avatar>
      )}
      {shown.map((id) => {
        const person = personById(id);
        const isOnline = online?.includes(id);
        return (
          <Tooltip key={id}>
            <TooltipTrigger
              render={
                <Avatar
                  size="xs"
                  className={cn(
                    isOnline && "ring-(--green-9) ring-1 ring-offset-1",
                  )}
                >
                  <AvatarFallback
                    className="text-[9px]"
                    style={{
                      background: `var(--${person.hue}-5)`,
                      color: `var(--${person.hue}-11)`,
                    }}
                  >
                    {person.initials}
                  </AvatarFallback>
                </Avatar>
              }
            />
            <TooltipContent side="top">
              {person.name}
              {isOnline ? " · online" : ""}
            </TooltipContent>
          </Tooltip>
        );
      })}
    </AvatarGroup>
  );
}

export function SectionLabel({
  children,
  count,
}: {
  children: React.ReactNode;
  count?: number;
}) {
  return (
    <div className="flex items-center gap-1.5 px-1 pt-4 pb-1.5 first:pt-1">
      <span className="font-semibold text-[11px] text-gray-10 uppercase tracking-wide">
        {children}
      </span>
      {count !== undefined && (
        <span className="rounded bg-gray-3 px-1 text-[10px] text-gray-10">
          {count}
        </span>
      )}
    </div>
  );
}
