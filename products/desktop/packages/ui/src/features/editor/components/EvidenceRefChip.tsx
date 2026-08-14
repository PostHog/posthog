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
import { type MouseEvent, type ReactNode, useId } from "react";
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

const SPARK_W = 100;
const SPARK_H = 32;
const SPARK_PAD = 3;

/**
 * Tiny trend line for the hover card, drawn from the numbers the link itself
 * carries — same zero-fetch principle as the other display params.
 */
function Sparkline({ points }: { points: number[] }) {
  const gradientId = useId();
  const max = Math.max(...points);
  const min = Math.min(...points);
  const range = max - min || 1;
  const coords = points.map((point, index) => [
    (index / (points.length - 1)) * SPARK_W,
    SPARK_H - SPARK_PAD - ((point - min) / range) * (SPARK_H - 2 * SPARK_PAD),
  ]);
  const line = coords
    .map(
      ([x, y], index) =>
        `${index === 0 ? "M" : "L"}${x.toFixed(1)} ${y.toFixed(1)}`,
    )
    .join(" ");
  const [lastX, lastY] = coords[coords.length - 1];
  return (
    <svg
      viewBox={`0 0 ${SPARK_W} ${SPARK_H}`}
      preserveAspectRatio="none"
      className="h-9 w-full"
      role="img"
      aria-label="Trend sparkline"
      data-testid="evidence-sparkline"
    >
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--accent-9)" stopOpacity={0.2} />
          <stop offset="100%" stopColor="var(--accent-9)" stopOpacity={0.02} />
        </linearGradient>
      </defs>
      <path
        d={`${line} L${SPARK_W} ${SPARK_H} L0 ${SPARK_H} Z`}
        fill={`url(#${gradientId})`}
      />
      <path
        d={line}
        fill="none"
        stroke="var(--accent-9)"
        strokeWidth={1.6}
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
      <circle cx={lastX} cy={lastY} r={2} fill="var(--accent-9)" />
    </svg>
  );
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
      {(target.value || target.desc || target.series) && (
        <div className="border-(--gray-a4) border-t px-3 py-2">
          <div className="flex items-center gap-3">
            {(target.value || target.desc) && (
              <span className="min-w-0 flex-1">
                {target.value && (
                  <span className="block font-[600] text-(--gray-12) text-[17px] tabular-nums leading-tight tracking-[-0.01em]">
                    {target.value}
                  </span>
                )}
                {target.desc && (
                  <span
                    className={`block text-(--gray-10) text-[11.5px] leading-snug ${target.value ? "mt-1" : ""}`}
                  >
                    {target.desc}
                  </span>
                )}
              </span>
            )}
            {target.series && (
              <span
                className={
                  target.value || target.desc
                    ? "w-24 shrink-0"
                    : "min-w-0 flex-1"
                }
              >
                <Sparkline points={target.series} />
              </span>
            )}
          </div>
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
