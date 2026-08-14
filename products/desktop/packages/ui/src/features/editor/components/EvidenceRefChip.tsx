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
import { getObjectKind } from "../../../utils/objectKinds";

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
  const meta = getObjectKind(target.kind);
  const KindIcon = meta.icon;
  return (
    <div className="w-72 p-3">
      <div className="flex items-center gap-1.5 text-[10.5px] text-(--gray-9) uppercase tracking-[0.04em]">
        <KindIcon size={12} aria-hidden />
        <span className="truncate">{meta.kindLabel}</span>
        <span className="ml-auto shrink-0 normal-case tracking-normal">
          {meta.source}
        </span>
      </div>
      {preview === undefined ? (
        <div
          className="mt-2.5 space-y-1.5"
          data-testid="evidence-preview-loading"
        >
          <div className="h-3.5 w-3/5 animate-pulse rounded bg-(--gray-a4)" />
          <div className="h-2.5 w-2/5 animate-pulse rounded bg-(--gray-a3)" />
        </div>
      ) : preview ? (
        <div className="mt-2" data-testid="evidence-preview">
          <span className="block font-semibold text-(--gray-12) text-[14px] leading-snug">
            {preview.title}
          </span>
          {preview.detail && (
            <span className="mt-1 block text-(--gray-10) text-[11.5px] leading-snug">
              {preview.detail}
            </span>
          )}
        </div>
      ) : (
        <div className="mt-2">
          <span className="block font-semibold text-(--gray-12) text-[14px] leading-snug">
            {children}
          </span>
        </div>
      )}
      <div className="mt-2.5 flex items-center justify-between gap-3 text-[10.5px]">
        <span className="truncate font-mono text-(--gray-8)">{target.id}</span>
        {clickable && (
          <span className="shrink-0 text-(--gray-10)">Opens in PostHog ↗</span>
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
