import { ArrowSquareOut } from "@phosphor-icons/react";
import {
  compactNumber,
  relativeTime,
  stalenessLabel,
} from "@posthog/core/code-editor/enrichmentPresenters";
import { Badge, Button, Card } from "@posthog/quill";
import type { SerializedEvent, SerializedFlag } from "@posthog/shared";
import {
  eventDefinitionUrl,
  experimentUrl,
  flagUrl,
  flagUrlByKey,
  type LinkOverrides,
} from "@posthog/ui/utils/posthogLinks";
import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { openExternalUrl } from "../../../shell/openExternal";
import { useAuthStateValue } from "../../auth/store";
import { useEnrichmentPopoverStore } from "../stores/enrichmentPopoverStore";

const POPOVER_WIDTH = 320;
const GAP = 8;

function openExternal(url: string) {
  openExternalUrl(url);
}

function FlagBody({
  flag,
  linkOverrides,
}: {
  flag: SerializedFlag;
  linkOverrides: LinkOverrides;
}) {
  const href =
    flag.flagId !== null
      ? flagUrl(flag.flagId, linkOverrides)
      : flagUrlByKey(flag.flagKey, linkOverrides);
  const expHref = flag.experiment
    ? experimentUrl(flag.experiment.id, linkOverrides)
    : null;

  return (
    <div className="flex flex-col gap-2 px-3 py-2">
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <Badge variant="info">Flag</Badge>
          <span className="truncate font-mono text-sm" title={flag.flagKey}>
            {flag.flagKey}
          </span>
        </div>
        <Badge variant="default">{flag.flagType}</Badge>
      </div>

      {flag.staleness && (
        <div>
          <Badge
            variant={flag.staleness === "inactive" ? "destructive" : "warning"}
          >
            {stalenessLabel(flag.staleness)}
          </Badge>
        </div>
      )}

      {flag.rollout !== null && flag.variants.length === 0 && (
        <div>
          <div className="mb-1 flex justify-between text-muted-foreground text-xs">
            <span>Rollout</span>
            <span>{flag.rollout}%</span>
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded bg-[var(--gray-4)]">
            <div
              className="h-full bg-[var(--accent-9)]"
              style={{ width: `${Math.min(100, Math.max(0, flag.rollout))}%` }}
            />
          </div>
        </div>
      )}

      {flag.variants.length > 0 && (
        <div className="flex flex-col gap-1">
          <div className="text-muted-foreground text-xs">Variants</div>
          <div className="flex flex-col gap-1">
            {flag.variants.map((v) => (
              <div
                key={v.key}
                className="flex items-center justify-between text-xs"
              >
                <span className="font-mono">{v.key}</span>
                <span className="text-muted-foreground">
                  {v.rolloutPercentage}%
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {flag.experiment && (
        <div className="flex items-center justify-between gap-2 rounded border border-[var(--gray-5)] p-2 text-xs">
          <div className="min-w-0">
            <div className="text-muted-foreground">Experiment</div>
            <div className="truncate" title={flag.experiment.name}>
              {flag.experiment.name}
            </div>
          </div>
          <Badge
            variant={
              flag.experiment.status === "running" ? "success" : "default"
            }
          >
            {flag.experiment.status}
          </Badge>
        </div>
      )}

      <div className="flex gap-2 pt-1">
        {href && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => openExternal(href)}
          >
            <ArrowSquareOut size={12} weight="bold" />
            Open flag
          </Button>
        )}
        {expHref && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => openExternal(expHref)}
          >
            <ArrowSquareOut size={12} weight="bold" />
            Experiment
          </Button>
        )}
      </div>
    </div>
  );
}

function EventBody({
  event,
  linkOverrides,
}: {
  event: SerializedEvent;
  linkOverrides: LinkOverrides;
}) {
  const href = event.definitionId
    ? eventDefinitionUrl(event.definitionId, linkOverrides)
    : null;
  const lastSeen = relativeTime(event.lastSeenAt);

  return (
    <div className="flex flex-col gap-2 px-3 py-2">
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <Badge variant="info">Event</Badge>
          <span className="truncate font-mono text-sm" title={event.eventName}>
            {event.eventName}
          </span>
        </div>
        {event.verified && <Badge variant="success">Verified</Badge>}
      </div>

      {event.description && (
        <div className="text-muted-foreground text-xs">{event.description}</div>
      )}

      <div className="grid grid-cols-2 gap-2 text-xs">
        {event.volume !== null && (
          <div>
            <div className="text-muted-foreground">30-day volume</div>
            <div className="font-medium">{compactNumber(event.volume)}</div>
          </div>
        )}
        {event.uniqueUsers !== null && (
          <div>
            <div className="text-muted-foreground">Unique users</div>
            <div className="font-medium">
              {compactNumber(event.uniqueUsers)}
            </div>
          </div>
        )}
        {lastSeen && (
          <div className="col-span-2">
            <div className="text-muted-foreground">Last seen</div>
            <div className="font-medium">{lastSeen}</div>
          </div>
        )}
      </div>

      {event.tags.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {event.tags.map((tag) => (
            <Badge key={tag} variant="default">
              {tag}
            </Badge>
          ))}
        </div>
      )}

      {href && (
        <div className="pt-1">
          <Button
            size="sm"
            variant="outline"
            onClick={() => openExternal(href)}
          >
            <ArrowSquareOut size={12} weight="bold" />
            Open event
          </Button>
        </div>
      )}
    </div>
  );
}

export function EnrichmentPopover() {
  const open = useEnrichmentPopoverStore((s) => s.open);
  const entry = useEnrichmentPopoverStore((s) => s.entry);
  const anchorRect = useEnrichmentPopoverStore((s) => s.anchorRect);
  const close = useEnrichmentPopoverStore((s) => s.close);
  const projectId = useAuthStateValue((s) => s.currentProjectId);
  const cloudRegion = useAuthStateValue((s) => s.cloudRegion);
  const ref = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!ref.current) return;
      if (!ref.current.contains(e.target as Node)) close();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open, close]);

  if (!open || !entry || !anchorRect) return null;

  const viewportWidth = window.innerWidth;
  const viewportHeight = window.innerHeight;
  const preferredLeft = anchorRect.right + GAP;
  const fitsRight = preferredLeft + POPOVER_WIDTH + 8 <= viewportWidth;
  const left = fitsRight
    ? preferredLeft
    : Math.max(8, anchorRect.left - POPOVER_WIDTH - GAP);
  const top = Math.max(8, Math.min(anchorRect.top, viewportHeight - 200));

  return createPortal(
    <div
      ref={ref}
      style={{
        position: "fixed",
        top,
        left,
        width: POPOVER_WIDTH,
        zIndex: 1000,
      }}
    >
      <Card size="sm" className="gap-0 py-0 shadow-lg">
        {entry.kind === "flag" ? (
          <FlagBody
            flag={entry.data}
            linkOverrides={{ projectId, cloudRegion }}
          />
        ) : (
          <EventBody
            event={entry.data}
            linkOverrides={{ projectId, cloudRegion }}
          />
        )}
      </Card>
    </div>,
    document.body,
  );
}
