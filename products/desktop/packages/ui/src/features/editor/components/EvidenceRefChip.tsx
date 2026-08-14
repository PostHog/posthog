import { getCloudUrlFromRegion } from "@posthog/shared";
import { type MouseEvent, type ReactNode, useId, useState } from "react";
import { useOptionalAuthenticatedClient } from "../../../features/auth/authClient";
import { useAuthStateValue } from "../../../features/auth/store";
import { useAuthenticatedQuery } from "../../../hooks/useAuthenticatedQuery";
import { Tooltip } from "../../../primitives/Tooltip";
import { openExternalUrl } from "../../../shell/openExternal";
import {
  type EvidenceLinkTarget,
  evidenceWebPath,
} from "../../../utils/evidenceLinks";
import { getObjectKind } from "../../../utils/objectKinds";
import {
  type EvidenceCardData,
  fetchEvidencePreview,
} from "../evidencePreview";

/**
 * Inline evidence reference inside an agent message, authored as a
 * `<kind id="...">label</kind>` object tag (see remarkObjectTags).
 *
 * Renders as a dotted-underline span with a small kind icon, so it reads as
 * part of the sentence and wraps like text. The underline is a bottom border
 * rather than text-decoration: decoration never paints under an atomic
 * inline like the icon's svg, while a bottom border runs under the full
 * reference on every wrapped line fragment.
 *
 * The reference carries only `kind/id`. Hovering mounts the card, which
 * resolves the object's live name and status through the PostHog API (for
 * `hogql`, runs the query); clicking opens the object in PostHog at a URL
 * derived from the reference and the current project. Nothing about the
 * object is stored in the message itself.
 */

const SPARK_W = 100;
const SPARK_H = 30;
const SPARK_PAD = 2;
// PostHog's first data-viz color, same source quill-charts reads; the hex
// fallback keeps the spark on-brand where the theme variable isn't defined
// (the tooltip portals outside the theme root).
const SPARK_COLOR = "var(--data-color-1, #1d4aff)";

/** Mini chart of the preview's primary series: a line for time series, columns for categories. */
function Sparkline({
  points,
  render,
}: {
  points: number[];
  render: "line" | "bar";
}) {
  const gradientId = useId();
  const max = Math.max(...points);
  const min = render === "bar" ? Math.min(0, ...points) : Math.min(...points);
  const range = max - min || 1;
  const scaleY = (value: number): number =>
    SPARK_H - SPARK_PAD - ((value - min) / range) * (SPARK_H - 2 * SPARK_PAD);

  if (render === "bar") {
    const step = SPARK_W / points.length;
    const gap = Math.min(step * 0.25, 2);
    return (
      <svg
        viewBox={`0 0 ${SPARK_W} ${SPARK_H}`}
        preserveAspectRatio="none"
        className="h-9 w-full"
        role="img"
        aria-label="Column sparkline"
        data-testid="evidence-sparkline"
      >
        {points.map((point, index) => (
          <rect
            // biome-ignore lint/suspicious/noArrayIndexKey: static series, never reorders
            key={index}
            x={index * step + gap / 2}
            width={step - gap}
            y={scaleY(point)}
            height={Math.max(SPARK_H - SPARK_PAD - scaleY(point), 0.5)}
            fill={SPARK_COLOR}
            fillOpacity={0.85}
          />
        ))}
      </svg>
    );
  }

  const coords = points.map(
    (point, index) =>
      [
        points.length === 1 ? 0 : (index / (points.length - 1)) * SPARK_W,
        scaleY(point),
      ] as const,
  );
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
          <stop offset="0%" stopColor={SPARK_COLOR} stopOpacity={0.25} />
          <stop offset="100%" stopColor={SPARK_COLOR} stopOpacity={0.02} />
        </linearGradient>
      </defs>
      <path
        d={`${line} L${SPARK_W} ${SPARK_H} L0 ${SPARK_H} Z`}
        fill={`url(#${gradientId})`}
      />
      <path
        d={line}
        fill="none"
        stroke={SPARK_COLOR}
        strokeWidth={1.6}
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
      <circle cx={lastX} cy={lastY} r={2} fill={SPARK_COLOR} />
    </svg>
  );
}

/**
 * The hover card, presentation only. `preview` is the live lookup result:
 * `undefined` while loading, `null` when there is nothing to show (unknown
 * kind, failed lookup, or no session).
 */
export function EvidenceHoverCard({
  target,
  children,
  url,
  preview,
  onOpen = openExternalUrl,
}: {
  target: EvidenceLinkTarget;
  children: ReactNode;
  url: string | null;
  preview: EvidenceCardData | null | undefined;
  onOpen?: (url: string) => void;
}) {
  const meta = getObjectKind(target.kind);
  const KindIcon = meta.icon;
  const isQuery = target.kind === "hogql";
  const [showQuery, setShowQuery] = useState(false);
  return (
    <div className="w-80 p-3.5">
      <div className="flex items-center gap-1.5 text-[10.5px] text-(--gray-9)">
        <KindIcon size={12} aria-hidden />
        <span className="truncate uppercase tracking-[0.06em]">
          {meta.kindLabel}
        </span>
        {/* For a query the source label duplicates the footer's open action. */}
        {!isQuery && <span className="ml-auto shrink-0">{meta.source}</span>}
      </div>
      {preview === undefined ? (
        <div className="mt-3 space-y-2" data-testid="evidence-preview-loading">
          <div className="h-4 w-3/5 animate-pulse rounded bg-(--gray-a4)" />
          <div className="h-9 w-full animate-pulse rounded bg-(--gray-a3)" />
        </div>
      ) : preview ? (
        <div className="mt-2.5" data-testid="evidence-preview">
          <div className="flex items-baseline justify-between gap-3">
            <span className="min-w-0 truncate font-semibold text-(--gray-12) text-[14px] leading-snug">
              {preview.title}
            </span>
            {preview.headline && (
              <span className="flex shrink-0 items-baseline gap-1">
                <span className="font-semibold text-(--gray-12) text-[15px] tabular-nums leading-none">
                  {preview.headline.value}
                </span>
                {preview.headline.delta && (
                  <span
                    className={`font-medium text-[11px] tabular-nums ${
                      preview.headline.delta.direction === "up"
                        ? "text-(--green-11)"
                        : "text-(--red-11)"
                    }`}
                  >
                    {preview.headline.delta.direction === "up" ? "▲" : "▼"}
                    {preview.headline.delta.label}
                  </span>
                )}
              </span>
            )}
          </div>
          {preview.spark && preview.spark.points.length > 1 && (
            <div className="mt-2.5">
              <Sparkline
                points={preview.spark.points}
                render={preview.spark.render}
              />
            </div>
          )}
          {preview.detail && (
            <div className="mt-1.5 text-(--gray-10) text-[11.5px] leading-snug">
              {preview.detail}
            </div>
          )}
          {preview.facts && preview.facts.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {preview.facts.map((fact) => (
                <span
                  key={fact}
                  className="max-w-full truncate rounded-[4px] bg-(--gray-a3) px-1.5 py-0.5 text-(--gray-11) text-[10px]"
                >
                  {fact}
                </span>
              ))}
            </div>
          )}
        </div>
      ) : (
        <div className="mt-2.5">
          <span className="block font-semibold text-(--gray-12) text-[14px] leading-snug">
            {children}
          </span>
        </div>
      )}
      {isQuery && showQuery && (
        <div className="mt-3 max-h-36 overflow-y-auto rounded-[4px] bg-(--gray-a3) p-2">
          <pre
            className="m-0 select-text whitespace-pre-wrap break-all font-mono text-(--gray-11) text-[10.5px] leading-relaxed"
            data-testid="evidence-query"
          >
            {target.id}
          </pre>
        </div>
      )}
      <div className="mt-3 flex items-center justify-between gap-3 text-[10.5px]">
        {isQuery ? (
          <button
            type="button"
            onClick={() => setShowQuery((open) => !open)}
            className="min-w-0 cursor-pointer truncate border-none bg-transparent p-0 text-left font-mono text-(--gray-8) transition-colors hover:text-(--gray-11)"
          >
            {showQuery ? "Hide query" : target.id}
          </button>
        ) : (
          <span className="truncate font-mono text-(--gray-8)">
            {target.id}
          </span>
        )}
        {url && (
          <button
            type="button"
            onClick={() => onOpen(url)}
            className="shrink-0 cursor-pointer border-none bg-transparent p-0 text-(--gray-10) text-[10.5px] transition-colors hover:text-(--gray-12)"
          >
            Open in PostHog ↗
          </button>
        )}
      </div>
    </div>
  );
}

/**
 * Fetching wrapper around the card. Mounted only while the tooltip is open,
 * so the lookup is lazy: a transcript full of references costs nothing until
 * one is hovered, and react-query caches the result across hovers.
 */
function EvidenceHoverCardLoader({
  target,
  children,
  url,
}: {
  target: EvidenceLinkTarget;
  children: ReactNode;
  url: string | null;
}) {
  const client = useOptionalAuthenticatedClient();
  const query = useAuthenticatedQuery(
    ["evidence-preview", target.kind, target.id],
    (apiClient) => fetchEvidencePreview(apiClient, target),
    {
      staleTime: 5 * 60 * 1000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  );
  // No session means no lookup: show the static card, not an endless skeleton.
  const preview =
    !client || query.isError
      ? null
      : query.isFetched
        ? (query.data ?? null)
        : undefined;
  return (
    <EvidenceHoverCard target={target} url={url} preview={preview}>
      {children}
    </EvidenceHoverCard>
  );
}

export function EvidenceRefChip({
  target,
  children,
}: {
  target: EvidenceLinkTarget;
  children: ReactNode;
}) {
  const meta = getObjectKind(target.kind);
  const KindIcon = meta.icon;
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const cloudRegion = useAuthStateValue((state) => state.cloudRegion);

  const path = evidenceWebPath(target.kind, target.id);
  const url =
    path && cloudRegion && projectId
      ? `${getCloudUrlFromRegion(cloudRegion)}/project/${projectId}${path}`
      : null;

  const open = (event: MouseEvent<HTMLAnchorElement>) => {
    event.preventDefault();
    if (url) openExternalUrl(url);
  };

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
    <Tooltip
      content={
        <EvidenceHoverCardLoader target={target} url={url}>
          {children}
        </EvidenceHoverCardLoader>
      }
      contentClassName="block p-0"
      sideOffset={8}
    >
      {url ? (
        <a href={url} onClick={open} className={refClass}>
          {inner}
        </a>
      ) : (
        <span className={refClass}>{inner}</span>
      )}
    </Tooltip>
  );
}
