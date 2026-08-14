import {
  BugIcon,
  ChartLineIcon,
  ChatCircleTextIcon,
  ClipboardTextIcon,
  CursorClickIcon,
  FlagIcon,
  FlaskIcon,
  type Icon,
  LightningIcon,
  PlayCircleIcon,
  PulseIcon,
  ShieldCheckIcon,
  SparkleIcon,
  SquaresFourIcon,
  UserIcon,
  UsersThreeIcon,
} from "@phosphor-icons/react";
import type { EvidencePreview } from "@posthog/api-client/evidence-previews";
import { getCloudUrlFromRegion } from "@posthog/shared";
import type { MouseEvent, ReactNode } from "react";
import { useOptionalAuthenticatedClient } from "../../../features/auth/authClient";
import { useAuthStateValue } from "../../../features/auth/store";
import { useAuthenticatedQuery } from "../../../hooks/useAuthenticatedQuery";
import { Tooltip } from "../../../primitives/Tooltip";
import { openExternalUrl } from "../../../shell/openExternal";
import {
  type EvidenceLinkTarget,
  evidenceWebPath,
} from "../../../utils/evidenceLinks";

/**
 * Inline evidence reference inside an agent message.
 *
 * Renders as a dotted-underline span with a small kind icon, so it reads as
 * part of the sentence and wraps like text. The underline is a bottom border
 * rather than text-decoration: decoration never paints under an atomic
 * inline like the icon's svg, while a bottom border runs under the full
 * reference on every wrapped line fragment.
 *
 * The link carries only `kind/id`. Hovering mounts the card, which resolves
 * the object's live name and status through the PostHog API; clicking opens
 * the object in PostHog at a URL derived from the reference and the current
 * project. Nothing about the object is stored in the message itself.
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
  dashboard: {
    icon: SquaresFourIcon,
    kindLabel: "Dashboard",
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
  trace: {
    icon: SparkleIcon,
    kindLabel: "LLM trace",
    source: "AI observability",
  },
  eval: {
    icon: ShieldCheckIcon,
    kindLabel: "Evaluation",
    source: "AI evals",
  },
  event: {
    icon: LightningIcon,
    kindLabel: "Events",
    source: "Product analytics",
  },
  cohort: {
    icon: UsersThreeIcon,
    kindLabel: "Cohort",
    source: "Product analytics",
  },
  action: {
    icon: CursorClickIcon,
    kindLabel: "Action",
    source: "Product analytics",
  },
  person: {
    icon: UserIcon,
    kindLabel: "Person",
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

/**
 * The hover card, presentation only. `preview` is the live lookup result:
 * `undefined` while loading, `null` when there is nothing to show (unknown
 * kind, failed lookup, or no session).
 */
export function EvidenceHoverCard({
  target,
  children,
  clickable,
  preview,
}: {
  target: EvidenceLinkTarget;
  children: ReactNode;
  clickable: boolean;
  preview: EvidencePreview | null | undefined;
}) {
  const meta = getEvidenceKindMeta(target.kind);
  const KindIcon = meta.icon;
  return (
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
      {preview === undefined && (
        <div
          className="space-y-1.5 border-(--gray-a4) border-t px-3 py-2.5"
          data-testid="evidence-preview-loading"
        >
          <div className="h-3 w-3/5 animate-pulse rounded bg-(--gray-a4)" />
          <div className="h-2.5 w-2/5 animate-pulse rounded bg-(--gray-a3)" />
        </div>
      )}
      {preview && (
        <div
          className="border-(--gray-a4) border-t px-3 py-2"
          data-testid="evidence-preview"
        >
          <span className="block truncate font-medium text-(--gray-12) text-[12.5px] leading-[1.4]">
            {preview.title}
          </span>
          {preview.detail && (
            <span className="mt-0.5 block text-(--gray-10) text-[11.5px] leading-snug">
              {preview.detail}
            </span>
          )}
        </div>
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
}

/**
 * Fetching wrapper around the card. Mounted only while the tooltip is open,
 * so the lookup is lazy: a transcript full of references costs nothing until
 * one is hovered, and react-query caches the result across hovers.
 */
function EvidenceHoverCardLoader({
  target,
  children,
  clickable,
}: {
  target: EvidenceLinkTarget;
  children: ReactNode;
  clickable: boolean;
}) {
  const client = useOptionalAuthenticatedClient();
  const query = useAuthenticatedQuery(
    ["evidence-preview", target.kind, target.id],
    (apiClient) => apiClient.getEvidencePreview(target.kind, target.id),
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
    <EvidenceHoverCard target={target} clickable={clickable} preview={preview}>
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
  const meta = getEvidenceKindMeta(target.kind);
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
        <EvidenceHoverCardLoader target={target} clickable={!!url}>
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
