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
import type { MouseEvent, ReactNode } from "react";
import { Tooltip } from "../../../primitives/Tooltip";
import { openExternalUrl } from "../../../shell/openExternal";
import type { EvidenceLinkTarget } from "../../../utils/evidenceLinks";

/**
 * Inline evidence reference inside an agent message.
 *
 * Renders as a dotted-underline span with a small kind icon, so it reads as
 * part of the sentence and wraps like text. Hovering shows a preview card
 * with what the reference points at; clicking opens the underlying object in
 * PostHog when the link carries a `url`.
 *
 * UI layer only: the card shows the metadata the link itself carries. A live
 * data preview can slot into `preview` once evidence fetching exists.
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
  /** Slot for a live data preview inside the card, once fetching exists. */
  preview?: ReactNode;
}) {
  const meta = getEvidenceKindMeta(target.kind);
  const KindIcon = meta.icon;
  const clickable = !!target.url;

  const open = (event: MouseEvent<HTMLAnchorElement>) => {
    event.preventDefault();
    if (target.url) openExternalUrl(target.url);
  };

  const card = (
    <div className="w-60">
      <div className="flex items-center gap-2 px-2.5 py-2">
        <span className="flex size-5 shrink-0 items-center justify-center rounded-[5px] bg-(--gray-4)">
          <KindIcon size={12} className="text-(--gray-11)" aria-hidden />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate font-medium text-(--gray-12) text-xs leading-[1.35]">
            {children}
          </span>
          <span className="block text-(--gray-10) text-[11px] leading-[1.35]">
            {meta.kindLabel} · {meta.source}
          </span>
        </span>
      </div>
      {preview && <div className="px-2.5 pb-2">{preview}</div>}
      <div className="flex items-center justify-between gap-3 border-(--gray-4) border-t px-2.5 py-1.5 text-(--gray-9) text-[10.5px]">
        <span className="truncate font-mono">{target.id}</span>
        {clickable && (
          <span className="shrink-0 text-(--gray-10)">Opens in PostHog ↗</span>
        )}
      </div>
    </div>
  );

  const refClass =
    "text-(--gray-12) underline decoration-(--gray-8) decoration-dotted underline-offset-[3px] hover:decoration-(--gray-11) hover:decoration-solid";
  const inner = (
    <>
      {/* inline-block escapes the ancestor underline, keeping it off the icon */}
      <span className="mr-[3px] inline-block align-[-1px]">
        <KindIcon size={11} className="text-(--gray-10)" aria-hidden />
      </span>
      {children}
    </>
  );

  return (
    <Tooltip content={card} contentClassName="block p-0" sideOffset={8}>
      {clickable ? (
        <a href={target.url} onClick={open} className={refClass}>
          {inner}
        </a>
      ) : (
        <span className={refClass}>{inner}</span>
      )}
    </Tooltip>
  );
}
