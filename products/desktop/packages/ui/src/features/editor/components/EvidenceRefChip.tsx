import { Popover } from "@base-ui/react/popover";
import { CheckIcon, CopyIcon } from "@phosphor-icons/react";
import { isPostHogObjectKind } from "@posthog/core/message-editor/content";
import { Button } from "@posthog/quill";
import { getCloudUrlFromRegion } from "@posthog/shared";
import { useQueryClient } from "@tanstack/react-query";
import {
  type MouseEvent,
  type ReactNode,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";
import { useOptionalAuthenticatedClient } from "../../../features/auth/authClient";
import { useAuthStateValue } from "../../../features/auth/store";
import { useDraftStore } from "../../../features/message-editor/draftStore";
import { usePanelLayoutStore } from "../../../features/panels/panelLayoutStore";
import { useSessionTaskId } from "../../../features/sessions/useSessionTaskId";
import { useAuthenticatedQuery } from "../../../hooks/useAuthenticatedQuery";
import { useCopy } from "../../../primitives/useCopy";
import { openExternalUrl } from "../../../shell/openExternal";
import {
  type EvidenceLinkTarget,
  evidenceWebPath,
} from "../../../utils/evidenceLinks";
import { getObjectKind } from "../../../utils/objectKinds";
import { ExperimentResultsSummary } from "../../posthog-objects/ExperimentResultsSummary";
import { buildEvidenceComposerContent } from "../evidenceComposer";
import {
  EVIDENCE_PREVIEW_STALE_TIME,
  type EvidenceCardData,
  evidencePreviewQueryKey,
} from "../evidencePreview";
import {
  fetchEvidencePreviewTimed,
  trackEvidencePreviewShown,
} from "../evidencePreviewAnalytics";
import { useEvidencePreviewPrefetch } from "../useEvidencePreviewPrefetch";

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
 * The reference carries only `kind/id`. Hovering or focusing mounts the card,
 * which resolves the object's live name and status through the PostHog API
 * (for `hogql`, runs the query); clicking a linked reference opens the object
 * in PostHog at a URL derived from the reference and the current project.
 * Nothing about the object is stored in the message itself.
 *
 * The card is a Base UI popover, not a tooltip: it holds real controls (the
 * query toggle, "Open in PostHog"), so it must be a focus-managed overlay —
 * Tab moves from the chip into the card and operates its buttons, Escape
 * closes, and assistive tech sees an interactive popup rather than the whole
 * card flattened into description text.
 */

const SPARK_W = 100;
const SPARK_H = 30;
const SPARK_PAD = 2;
// Surfaces with their own palette (the quick-ask panel) set
// --evidence-spark-color; everywhere else PostHog's first data-viz color
// applies, with a hex fallback because the tooltip portals outside the
// theme root.
const SPARK_COLOR = "var(--evidence-spark-color, var(--data-color-1, #1d4aff))";

/** Mini chart of the preview's primary series: a line for time series, columns for categories. */
export function EvidenceSparkline({
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
    const barWidth = step * 0.62;
    // Bars grow from the zero line, so a negative point extends below it.
    // Measuring to the chart bottom instead would shrink or invert them once
    // any point is negative (min drops below 0 and lifts the zero line).
    const baseline = scaleY(0);
    return (
      <svg
        viewBox={`0 0 ${SPARK_W} ${SPARK_H}`}
        preserveAspectRatio="none"
        className="my-1 h-8 w-full"
        role="img"
        aria-label="Column sparkline"
        data-testid="evidence-sparkline"
      >
        {points.map((point, index) => {
          const y = scaleY(point);
          return (
            <rect
              // biome-ignore lint/suspicious/noArrayIndexKey: static series, never reorders
              key={index}
              x={(index * step + (step - barWidth) / 2).toFixed(1)}
              width={barWidth.toFixed(1)}
              y={Math.min(y, baseline).toFixed(1)}
              height={Math.max(Math.abs(y - baseline), 0.5).toFixed(1)}
              rx={1.2}
              fill={SPARK_COLOR}
              fillOpacity={0.82}
            />
          );
        })}
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
      className="my-1 h-8 w-full"
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

export function EvidenceHoverCard({
  target,
  children,
  url,
  preview,
  loadState = preview === undefined ? "loading" : preview ? "ready" : "missing",
  onOpen = openExternalUrl,
  onExpand,
}: {
  target: EvidenceLinkTarget;
  children: ReactNode;
  url: string | null;
  preview: EvidenceCardData | null | undefined;
  loadState?: "loading" | "error" | "missing" | "ready";
  onOpen?: (url: string) => void;
  onExpand?: (label: string) => void;
}) {
  const meta = getObjectKind(target.kind);
  const KindIcon = meta.icon;
  const isQuery = target.kind === "hogql";
  const [showQuery, setShowQuery] = useState(false);
  const { copied, copy } = useCopy();
  return (
    <div className="w-80 p-3.5">
      <div className="flex items-center gap-1.5 text-(--gray-9) text-[10.5px]">
        <KindIcon size={12} aria-hidden />
        <span className="truncate uppercase tracking-[0.06em]">
          {meta.kindLabel}
        </span>
        {/* For a query the source label duplicates the footer's open action. */}
        {!isQuery && <span className="ml-auto shrink-0">{meta.source}</span>}
      </div>
      {target.kind === "experiment" && loadState !== "ready" ? (
        <div className="mt-3">
          <ExperimentResultsSummary
            display="compact"
            loadState={loadState}
            results={preview?.experimentResults}
          />
        </div>
      ) : loadState === "loading" ? (
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
              <EvidenceSparkline
                points={preview.spark.points}
                render={preview.spark.render}
              />
            </div>
          )}
          {(preview.status || preview.detail) && (
            <div className="mt-1.5 text-(--gray-10) text-[11.5px] leading-snug">
              {[preview.status?.label, preview.detail]
                .filter(Boolean)
                .join(" · ")}
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
          {target.kind === "experiment" && (
            <div className="mt-2.5">
              <ExperimentResultsSummary
                display="compact"
                loadState="ready"
                results={preview.experimentResults}
              />
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
        <div className="flex min-w-0 items-center gap-0.5">
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
          <button
            type="button"
            aria-label={copied ? "Reference copied" : "Copy reference"}
            onClick={() => copy(target.id)}
            className="inline-flex size-5 shrink-0 cursor-pointer items-center justify-center rounded-[4px] border-none bg-transparent p-0 text-(--gray-9) transition-colors hover:bg-(--gray-a3) hover:text-(--gray-12)"
          >
            {copied ? <CheckIcon size={11} /> : <CopyIcon size={11} />}
          </button>
        </div>
        <div className="flex shrink-0 items-center gap-1">
          {onExpand && (
            <Button
              variant="link"
              size="xs"
              onClick={() =>
                onExpand(
                  preview?.title ??
                    (typeof children === "string" ? children : target.id),
                )
              }
            >
              Ask about this
            </Button>
          )}
          {url && (
            <Button variant="link-muted" size="xs" onClick={() => onOpen(url)}>
              Open in PostHog ↗
            </Button>
          )}
        </div>
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
  onExpand,
}: {
  target: EvidenceLinkTarget;
  children: ReactNode;
  url: string | null;
  onExpand?: (label: string) => void;
}) {
  const client = useOptionalAuthenticatedClient();
  const queryClient = useQueryClient();
  const shownTrackedRef = useRef(false);
  const kind = target.kind;
  const id = target.id;
  useEffect(() => {
    if (shownTrackedRef.current) return;
    shownTrackedRef.current = true;
    const cached =
      queryClient.getQueryState(evidencePreviewQueryKey({ kind, id }))
        ?.status === "success";
    trackEvidencePreviewShown(kind, cached);
  }, [queryClient, kind, id]);
  const query = useAuthenticatedQuery(
    evidencePreviewQueryKey(target),
    (apiClient) => fetchEvidencePreviewTimed(apiClient, target, "hover"),
    {
      staleTime: EVIDENCE_PREVIEW_STALE_TIME,
      refetchOnWindowFocus: false,
      retry: 1,
      // The card unmounts when the tooltip closes, so without this a preview
      // that already failed would refetch on every hover (re-running a hogql
      // or error lookup against /query/); the static fallback covers the miss.
      retryOnMount: false,
    },
  );
  // No session means no lookup: show the static card, not an endless skeleton.
  const loadState = !client
    ? "missing"
    : query.isError
      ? "error"
      : query.isFetched
        ? query.data
          ? "ready"
          : "missing"
        : "loading";
  const preview = query.data ?? null;
  // A reference whose cited id has no page (an event name, a flag key) can
  // still link out once the preview resolves the canonical id.
  const resolvedUrl = useEvidenceUrl(
    target.kind,
    preview?.resolvedId ?? target.id,
  );
  return (
    <EvidenceHoverCard
      target={target}
      url={url ?? resolvedUrl}
      preview={preview}
      loadState={loadState}
      onExpand={onExpand}
    >
      {children}
    </EvidenceHoverCard>
  );
}

/** PostHog web URL for a reference in the current project, when it has one. */
export function useEvidenceUrl(kind: string, id: string): string | null {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const cloudRegion = useAuthStateValue((state) => state.cloudRegion);
  const path = evidenceWebPath(kind, id);
  if (!path || !cloudRegion || !projectId) return null;
  return `${getCloudUrlFromRegion(cloudRegion)}/project/${projectId}${path}`;
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
  const url = useEvidenceUrl(target.kind, target.id);
  const taskId = useSessionTaskId();
  const objectKind = isPostHogObjectKind(target.kind) ? target.kind : null;
  const [open, setOpen] = useState(false);
  const [triggerElement, setTriggerElement] = useState<HTMLElement | null>(
    null,
  );
  useEvidencePreviewPrefetch(target, triggerElement);
  const expand =
    taskId && objectKind
      ? (label: string) => {
          const actions = useDraftStore.getState().actions;
          actions.insertPendingContent(
            taskId,
            buildEvidenceComposerContent({
              kind: objectKind,
              id: target.id,
              label: `${meta.kindLabel}: ${label}`,
              currentDraft: actions.getDraft(taskId),
            }),
          );
          actions.requestFocus(taskId);
          setOpen(false);
        }
      : undefined;
  const openPostHogObjectTab = usePanelLayoutStore(
    (state) => state.openPostHogObjectTab,
  );

  const openReference = (event: MouseEvent<HTMLAnchorElement>) => {
    event.preventDefault();
    if (taskId) {
      openPostHogObjectTab(taskId, {
        kind: target.kind,
        id: target.id,
        name: typeof children === "string" ? children : target.id,
      });
      setOpen(false);
      return;
    }
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
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger
        openOnHover
        delay={200}
        closeDelay={100}
        nativeButton={false}
        // Focus opens the card the way the tooltip used to, so a keyboard
        // user can preview a linked reference whose Enter action navigates
        // to PostHog instead of toggling the popover.
        onFocus={() => setOpen(true)}
        render={
          url || taskId ? (
            // Keep the truthful role: Enter follows the link (opens the
            // object's page in the app, or in PostHog outside a session), it
            // does not act as a popover button.
            // biome-ignore lint/a11y/useSemanticElements: the element already is an <a>; the explicit role restores link semantics the popover trigger's role="button" would override
            <a
              ref={setTriggerElement}
              href={url ?? "#"}
              onClick={openReference}
              // biome-ignore lint/a11y/noRedundantRoles: not redundant — the popover trigger injects role="button" without it
              role="link"
              className={refClass}
            >
              {inner}
            </a>
          ) : (
            // No page to link to: the reference is a real popover trigger
            // (focusable, Enter/Space opens the card), since the card's
            // "Open in PostHog" action is the only route to the object.
            <span
              ref={setTriggerElement}
              className={`${refClass} cursor-pointer`}
            >
              {inner}
            </span>
          )
        }
      />
      {open && (
        <Popover.Portal>
          {/* Self-styled like primitives/Tooltip: quill's popover CSS isn't
              loaded on every surface that renders chips (see ChatMarkdown). */}
          <Popover.Positioner side="top" sideOffset={8} className="z-[9999]">
            <Popover.Popup
              data-testid="evidence-hover-card"
              className="rounded-[6px] border border-(--gray-4) bg-(--gray-2) text-(--gray-12) outline-none"
              style={{ boxShadow: "0 4px 12px rgba(0, 0, 0, 0.25)" }}
            >
              <EvidenceHoverCardLoader
                target={target}
                url={url}
                onExpand={expand}
              >
                {children}
              </EvidenceHoverCardLoader>
            </Popover.Popup>
          </Popover.Positioner>
        </Popover.Portal>
      )}
    </Popover.Root>
  );
}
