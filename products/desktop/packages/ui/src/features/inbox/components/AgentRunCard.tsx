import {
  isFinishedRunReport,
  isLiveRunReport,
  isQueuedRunReport,
} from "@posthog/core/inbox/reportMembership";
import { deriveHeadline } from "@posthog/core/inbox/reportPresentation";
import { formatRelativeTimeLong } from "@posthog/shared";
import type { SignalReport } from "@posthog/shared/types";
import {
  InboxMetaRow,
  InboxMetaSeparator,
  InboxMetaText,
} from "@posthog/ui/features/inbox/components/InboxMetaRow";
import { InboxMetaSourceStack } from "@posthog/ui/features/inbox/components/InboxMetaSourceStack";
import { InboxBadge } from "@posthog/ui/features/inbox/components/utils/InboxBadge";
import { hasKnownSourceProduct } from "@posthog/ui/features/inbox/components/utils/source-product-icons";
import { useNavigate } from "@tanstack/react-router";

export type RunVariant = "queued" | "live" | "completed" | "failed";

/** Single source of truth for the four-bucket lifecycle of a run-shaped report. */
export function resolveRunVariant(report: SignalReport): RunVariant {
  if (isQueuedRunReport(report)) return "queued";
  if (isLiveRunReport(report)) return "live";
  if (isFinishedRunReport(report)) {
    return report.status === "failed" ? "failed" : "completed";
  }
  return "live";
}

export const RUN_VARIANT_TIMESTAMP_LABEL: Record<RunVariant, string> = {
  queued: "Queued",
  live: "Started",
  completed: "Finished",
  failed: "Failed",
};

export interface VariantMeta {
  label: string;
  badgeTone: "default" | "info" | "success" | "destructive";
  orbClass: string;
  dotClass: string;
  ariaLabel: string;
}

export const VARIANT_META: Record<RunVariant, VariantMeta> = {
  queued: {
    label: "Queued",
    badgeTone: "default",
    orbClass: "bg-(--gray-3) ring-(--gray-5)",
    dotClass: "bg-(--gray-9)",
    ariaLabel: "Queued",
  },
  live: {
    label: "Running",
    badgeTone: "info",
    orbClass: "bg-(--blue-2) ring-(--blue-5)",
    dotClass: "bg-(--blue-10) animate-pulse",
    ariaLabel: "In progress",
  },
  completed: {
    label: "Completed",
    badgeTone: "success",
    orbClass: "bg-(--green-2) ring-(--green-5)",
    dotClass: "bg-(--green-9)",
    ariaLabel: "Completed",
  },
  failed: {
    label: "Failed",
    badgeTone: "destructive",
    orbClass: "bg-(--red-2) ring-(--red-5)",
    dotClass: "bg-(--red-9)",
    ariaLabel: "Failed",
  },
};

function pickTimestamp(report: SignalReport, variant: RunVariant): string {
  if (variant === "live") return report.created_at;
  return report.updated_at ?? report.created_at;
}

function RunStatusOrb({ meta }: { meta: VariantMeta }) {
  return (
    <div
      className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full ring-1 ring-inset ${meta.orbClass}`}
    >
      <span
        className={`block h-1.5 w-1.5 rounded-full ${meta.dotClass}`}
        role="img"
        aria-label={meta.ariaLabel}
      />
    </div>
  );
}

interface AgentRunCardProps {
  report: SignalReport;
}

export function AgentRunCard({ report }: AgentRunCardProps) {
  const navigate = useNavigate();
  const hasSource = hasKnownSourceProduct(report.source_products);
  const runId = `…-${report.id.split("-").pop() ?? report.id}`;
  const variant = resolveRunVariant(report);
  const meta = VARIANT_META[variant];
  const timestampSource = pickTimestamp(report, variant);
  const headline = deriveHeadline(report.summary);

  return (
    <button
      type="button"
      onClick={() =>
        navigate({
          to: "/inbox/runs/$reportId",
          params: { reportId: report.id },
        })
      }
      className="group relative flex w-full items-start gap-3 rounded-(--radius-2) border border-border bg-(--color-panel-solid) px-4 py-3.5 text-left transition duration-150 hover:border-(--gray-6) hover:bg-(--gray-2) hover:shadow-sm focus-visible:bg-(--gray-2) focus-visible:outline-none"
    >
      <div className="absolute top-3.5 right-4">
        <InboxBadge variant={meta.badgeTone}>{meta.label}</InboxBadge>
      </div>

      <RunStatusOrb meta={meta} />

      <div className="flex min-w-0 flex-1 flex-col gap-1.5">
        {/* Pad clear of the absolute status badge. */}
        <span className="wrap-break-word min-w-0 pr-20 font-semibold text-[14px] text-gray-11 leading-snug tracking-tight">
          {report.title ?? "Untitled run"}
        </span>
        {headline ? (
          <span className="wrap-break-word line-clamp-2 text-[12.5px] text-gray-10 leading-snug">
            {headline}
          </span>
        ) : null}
        <InboxMetaRow className="mt-1.5">
          {hasSource ? (
            <>
              <InboxMetaSourceStack sourceProducts={report.source_products} />
              <InboxMetaSeparator />
            </>
          ) : null}
          <InboxMetaText>
            {RUN_VARIANT_TIMESTAMP_LABEL[variant]}{" "}
            {formatRelativeTimeLong(timestampSource)}
          </InboxMetaText>
          <InboxMetaSeparator />
          <InboxMetaText mono className="text-[11px]">
            {runId}
          </InboxMetaText>
        </InboxMetaRow>
      </div>
    </button>
  );
}
