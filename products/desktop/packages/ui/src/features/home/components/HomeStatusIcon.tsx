import {
  CheckCircleIcon,
  CircleDashedIcon,
  CircleHalfIcon,
  CircleIcon,
  type Icon,
  ProhibitInsetIcon,
  WarningCircleIcon,
} from "@phosphor-icons/react";
import {
  HOME_STATUS_LABELS,
  type HomeStatus,
} from "@posthog/core/home/schemas";
import { Tooltip, TooltipContent, TooltipTrigger } from "@posthog/quill";

/**
 * The glyph and colour each status wears, everywhere it appears: the row, the
 * group heading, and the filter menu. One table keeps them from drifting apart,
 * which is what makes the column scannable at a glance.
 *
 * Colours are the theme's step-11 tokens, the readable step for a glyph rather
 * than a filled shape, matching the session dot vocabulary the sidebar uses.
 */
const STATUS_PRESENTATION: Record<
  HomeStatus,
  { icon: Icon; color: string; weight: "regular" | "fill" | "bold" }
> = {
  backlog: {
    icon: CircleDashedIcon,
    color: "var(--gray-10)",
    weight: "regular",
  },
  todo: { icon: CircleIcon, color: "var(--gray-11)", weight: "regular" },
  in_progress: {
    icon: CircleHalfIcon,
    color: "var(--primary)",
    weight: "fill",
  },
  done: { icon: CheckCircleIcon, color: "var(--green-11)", weight: "fill" },
  failed: { icon: WarningCircleIcon, color: "var(--red-11)", weight: "fill" },
  canceled: {
    icon: ProhibitInsetIcon,
    color: "var(--gray-10)",
    weight: "regular",
  },
};

export function HomeStatusIcon({
  status,
  size = 15,
  className,
}: {
  status: HomeStatus;
  size?: number;
  className?: string;
}) {
  const { icon: Glyph, color, weight } = STATUS_PRESENTATION[status];
  return (
    <Glyph
      size={size}
      weight={weight}
      color={color}
      className={className}
      aria-hidden
    />
  );
}

/** The row's status cell: the glyph alone, with its name on hover. */
export function HomeStatusCell({ status }: { status: HomeStatus }) {
  return (
    <Tooltip>
      <TooltipTrigger
        render={
          <span className="flex size-4 shrink-0 items-center justify-center">
            <HomeStatusIcon status={status} />
          </span>
        }
      />
      <TooltipContent>{HOME_STATUS_LABELS[status]}</TooltipContent>
    </Tooltip>
  );
}
