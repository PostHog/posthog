import {
  BugIcon,
  ChartLineIcon,
  ChatCircleTextIcon,
  ClipboardTextIcon,
  FlagIcon,
  FlaskIcon,
  type Icon,
  LightningIcon,
  PlayCircleIcon,
  PulseIcon,
  ShieldCheckIcon,
  SparkleIcon,
} from "@phosphor-icons/react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@posthog/quill";
import type { ReactNode } from "react";
import { openExternalUrl } from "../../../shell/openExternal";
import type { EvidenceLinkTarget } from "../../../utils/evidenceLinks";

/**
 * Inline evidence reference inside an agent message.
 *
 * Renders as a quiet dotted-underline span with a small kind icon, so it reads
 * as part of the sentence rather than a UI element. Hovering shows a preview
 * popover with what the reference points at; clicking opens the underlying
 * object in PostHog when the link carries a `url`.
 *
 * UI layer only: the popover shows the metadata the link itself carries. A
 * live data preview can slot into `preview` once evidence fetching exists.
 */

interface EvidenceKindMeta {
  icon: Icon;
  /** Human name of the evidence kind, e.g. "Insight". */
  kindLabel: string;
  /** Product the evidence comes from, e.g. "Product analytics". */
  source: string;
}

const EVIDENCE_KIND_META: Record<string, EvidenceKindMeta> = {
  insight: {
    icon: ChartLineIcon,
    kindLabel: "Insight",
    source: "Product analytics",
  },
  error: { icon: BugIcon, kindLabel: "Error issue", source: "Error tracking" },
  replay: {
    icon: PlayCircleIcon,
    kindLabel: "Session replay",
    source: "Session replay",
  },
  flag: { icon: FlagIcon, kindLabel: "Feature flag", source: "Feature flags" },
  experiment: {
    icon: FlaskIcon,
    kindLabel: "Experiment",
    source: "Experiments",
  },
  survey: { icon: ClipboardTextIcon, kindLabel: "Survey", source: "Surveys" },
  ticket: {
    icon: ChatCircleTextIcon,
    kindLabel: "Support tickets",
    source: "Conversations",
  },
  trace: { icon: SparkleIcon, kindLabel: "LLM trace", source: "LLM analytics" },
  eval: {
    icon: ShieldCheckIcon,
    kindLabel: "Evaluation",
    source: "LLM analytics",
  },
  event: {
    icon: LightningIcon,
    kindLabel: "Events",
    source: "Product analytics",
  },
};

const GENERIC_KIND_META: EvidenceKindMeta = {
  icon: PulseIcon,
  kindLabel: "Evidence",
  source: "PostHog",
};

export function getEvidenceKindMeta(kind: string): EvidenceKindMeta {
  return EVIDENCE_KIND_META[kind] ?? GENERIC_KIND_META;
}

export function EvidenceRefChip({
  target,
  children,
  preview,
}: {
  target: EvidenceLinkTarget;
  children: ReactNode;
  /** Slot for a live data preview inside the popover, once fetching exists. */
  preview?: ReactNode;
}) {
  const meta = getEvidenceKindMeta(target.kind);
  const KindIcon = meta.icon;
  const clickable = !!target.url;

  const refElement = (
    <button
      type="button"
      onClick={
        clickable && target.url
          ? () => openExternalUrl(target.url as string)
          : undefined
      }
      className={`m-0 inline border-(--gray-8) border-0 border-b border-dotted bg-transparent p-0 pb-px text-left align-baseline font-inherit text-(--gray-12) text-[length:inherit] leading-inherit hover:border-(--accent-9) hover:border-solid ${clickable ? "cursor-pointer" : "cursor-default"}`}
    >
      <KindIcon
        size={11}
        className="mr-1 inline-block align-[-1px] text-(--gray-10)"
        aria-hidden
      />
      {children}
    </button>
  );

  return (
    <Tooltip>
      <TooltipTrigger render={refElement} />
      <TooltipContent side="top" sideOffset={6} className="w-64 p-0">
        <div className="flex items-center gap-2 px-3 pt-2.5 pb-1.5">
          <span className="flex size-6 shrink-0 items-center justify-center rounded-md bg-(--gray-4)">
            <KindIcon size={13} className="text-(--gray-11)" aria-hidden />
          </span>
          <span className="min-w-0">
            <span className="block truncate font-medium text-(--gray-12) text-xs">
              {children}
            </span>
            <span className="block text-(--gray-10) text-[11px]">
              {meta.kindLabel} · {meta.source}
            </span>
          </span>
        </div>
        {preview && <div className="px-3 pb-1.5">{preview}</div>}
        <div className="flex items-center justify-between border-(--gray-4) border-t px-3 py-1.5 text-(--gray-10) text-[11px]">
          <span className="truncate font-mono">{target.id}</span>
          {clickable && <span className="shrink-0">Opens in PostHog ↗</span>}
        </div>
      </TooltipContent>
    </Tooltip>
  );
}
