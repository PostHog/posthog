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
 * part of the sentence and wraps like text. The underline is a bottom border
 * rather than text-decoration: decoration never paints under an atomic
 * inline like the icon's svg, while a bottom border runs under the full
 * reference on every wrapped line fragment.
 *
 * Hovering shows a preview card with what the reference points at; clicking
 * opens the underlying object in PostHog when the link carries a `url`.
 *
 * UI layer only: the card shows the metadata the link itself carries
 * (including the optional `value` and `desc` display params). A live data
 * preview can slot into `preview` once evidence fetching exists.
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
    <div className="w-72">
      <div className="flex items-center gap-2.5 px-3 pt-2.5 pb-2">
        <span className="flex size-6 shrink-0 items-center justify-center rounded-md border border-(--gray-a4) bg-(--gray-a3)">
          <KindIcon size={14} className="text-(--gray-11)" aria-hidden />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate font-medium text-(--gray-12) text-[12.5px] leading-[1.4]">
            {children}
          </span>
          <span className="block text-(--gray-10) text-[11px] leading-[1.4]">
            {meta.kindLabel} · {meta.source}
          </span>
        </span>
      </div>
      {(target.value || target.desc) && (
        <div className="border-(--gray-a4) border-t px-3 py-2">
          {target.value && (
            <div className="font-[600] text-(--gray-12) text-[17px] leading-tight tracking-[-0.01em]">
              {target.value}
            </div>
          )}
          {target.desc && (
            <div
              className={`text-(--gray-10) text-[11.5px] leading-snug ${target.value ? "mt-1" : ""}`}
            >
              {target.desc}
            </div>
          )}
        </div>
      )}
      {preview && (
        <div className="border-(--gray-a4) border-t px-3 py-2">{preview}</div>
      )}
      <div className="flex items-center justify-between gap-3 rounded-b-[5px] border-(--gray-a4) border-t bg-(--gray-a2) px-3 py-[7px] text-[10.5px]">
        <span className="truncate font-mono text-(--gray-9)">{target.id}</span>
        {clickable ? (
          <span className="shrink-0 text-(--gray-11)">Opens in PostHog ↗</span>
        ) : (
          <span className="shrink-0 text-(--gray-9)">{meta.source}</span>
        )}
      </div>
    </div>
  );

  const refClass =
    "border-b border-dotted border-(--gray-a8) pb-px text-(--gray-12) no-underline hover:border-solid hover:border-(--gray-a11)";
  const inner = (
    <>
      <KindIcon
        size={12}
        className="mr-[3px] inline-block translate-y-[-1px] align-middle text-(--gray-10)"
        aria-hidden
      />
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
