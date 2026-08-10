import {
  ArrowSquareOutIcon,
  CheckCircleIcon,
  CheckIcon,
  ChecksIcon,
  CircleNotchIcon,
  MinusCircleIcon,
  ProhibitIcon,
  XCircleIcon,
} from "@phosphor-icons/react";
import type { PrCheck, PrCheckBucket } from "@posthog/core/git/router-schemas";
import { Spinner } from "@posthog/quill";
import { DetailSection } from "@posthog/ui/features/inbox/components/DetailSection";
import { useMemo, useState } from "react";
import { openExternalUrl } from "../../shell/openExternal";
import { usePrChecks } from "./usePrChecks";

/** Display order: failed first, then running, then succeeded, skipped last. */
const BUCKET_META: Array<{
  bucket: PrCheckBucket;
  label: string;
  labelClass: string;
}> = [
  { bucket: "fail", label: "failed", labelClass: "text-(--red-11)" },
  { bucket: "cancel", label: "cancelled", labelClass: "text-gray-11" },
  { bucket: "pending", label: "running", labelClass: "text-(--amber-11)" },
  { bucket: "pass", label: "successful", labelClass: "text-(--green-11)" },
  { bucket: "skipping", label: "skipped", labelClass: "text-gray-10" },
];

const BUCKET_ORDER: Record<PrCheckBucket, number> = {
  fail: 0,
  cancel: 1,
  pending: 2,
  pass: 3,
  skipping: 4,
};

/** Buckets that need attention — shown by default. */
const DEFAULT_VISIBLE: PrCheckBucket[] = ["fail", "cancel", "pending"];

interface PrChecksSectionProps {
  prUrl: string;
}

/**
 * CI status list for a PR. The header carries one checkbox per status bucket
 * (failed, running, successful, …) that filters the rows below; only the
 * attention-worthy buckets (failed, running) are shown by default.
 */
export function PrChecksSection({ prUrl }: PrChecksSectionProps) {
  const checksQuery = usePrChecks(prUrl);
  const checks = checksQuery.data;
  const [visibleBuckets, setVisibleBuckets] = useState<Set<PrCheckBucket>>(
    () => new Set(DEFAULT_VISIBLE),
  );

  const sorted = useMemo(
    () =>
      [...(checks ?? [])].sort(
        (a, b) =>
          BUCKET_ORDER[a.bucket] - BUCKET_ORDER[b.bucket] ||
          checkLabel(a).localeCompare(checkLabel(b)),
      ),
    [checks],
  );

  const counts = useMemo(() => {
    const out: Record<PrCheckBucket, number> = {
      fail: 0,
      cancel: 0,
      pending: 0,
      pass: 0,
      skipping: 0,
    };
    for (const check of sorted) out[check.bucket]++;
    return out;
  }, [sorted]);

  if (checksQuery.isLoading) {
    return (
      <DetailSection Icon={ChecksIcon} title="Checks">
        <div className="flex items-center gap-2 py-1 text-[12px] text-gray-10">
          <Spinner />
          Loading checks…
        </div>
      </DetailSection>
    );
  }

  if (!checks) {
    return (
      <DetailSection Icon={ChecksIcon} title="Checks">
        <div className="py-1 text-[12px] text-gray-10">
          Couldn't load CI checks for this pull request.
        </div>
      </DetailSection>
    );
  }

  if (checks.length === 0) return null;

  const toggleBucket = (bucket: PrCheckBucket) => {
    setVisibleBuckets((prev) => {
      const next = new Set(prev);
      if (next.has(bucket)) next.delete(bucket);
      else next.add(bucket);
      return next;
    });
  };

  const visible = sorted.filter((check) => visibleBuckets.has(check.bucket));

  return (
    <DetailSection
      Icon={ChecksIcon}
      title="Checks"
      rightSlot={
        <span className="flex items-center gap-1">
          {BUCKET_META.map(({ bucket, label, labelClass }) =>
            counts[bucket] > 0 ? (
              <BucketFilterCheckbox
                key={bucket}
                checked={visibleBuckets.has(bucket)}
                onToggle={() => toggleBucket(bucket)}
                labelClass={labelClass}
                label={`${counts[bucket]} ${label}`}
              />
            ) : null,
          )}
        </span>
      }
    >
      {visible.length > 0 && (
        <div className="overflow-hidden rounded-md border border-(--gray-5)">
          {visible.map((check, index) => (
            <CheckRow
              key={`${check.workflow ?? ""}/${check.name}/${index}`}
              check={check}
            />
          ))}
        </div>
      )}
    </DetailSection>
  );
}

function BucketFilterCheckbox({
  checked,
  onToggle,
  label,
  labelClass,
}: {
  checked: boolean;
  onToggle: () => void;
  label: string;
  labelClass: string;
}) {
  return (
    <button
      type="button"
      aria-pressed={checked}
      onClick={onToggle}
      className="inline-flex shrink-0 cursor-pointer items-center gap-[5px] rounded border-0 bg-transparent px-[5px] py-[2px] text-[11px] hover:bg-gray-4"
    >
      <span
        className={`inline-flex h-[13px] w-[13px] items-center justify-center rounded-[3px] border ${
          checked
            ? "border-(--accent-9) bg-(--accent-9) text-white"
            : "border-(--gray-7)"
        }`}
      >
        {checked && <CheckIcon size={9} weight="bold" />}
      </span>
      <span className={`tabular-nums ${labelClass}`}>{label}</span>
    </button>
  );
}

function CheckRow({ check }: { check: PrCheck }) {
  return (
    <button
      type="button"
      onClick={() => {
        if (check.link) openExternalUrl(check.link);
      }}
      title={check.link ? "Open in GitHub" : undefined}
      className="flex w-full cursor-pointer items-center gap-2 border-0 border-b border-b-(--gray-5) bg-transparent px-3 py-[7px] text-left text-[12px] last:border-b-0 hover:bg-gray-2"
    >
      <CheckBucketIcon bucket={check.bucket} />
      <span className="shrink-0 font-medium text-gray-12">
        {checkLabel(check)}
      </span>
      {check.description && (
        <span className="min-w-0 flex-1 truncate text-gray-10">
          {check.description}
        </span>
      )}
      {check.link && (
        <ArrowSquareOutIcon
          size={12}
          className="ml-auto shrink-0 text-(--gray-9)"
        />
      )}
    </button>
  );
}

function checkLabel(check: PrCheck): string {
  return check.workflow ? `${check.workflow} / ${check.name}` : check.name;
}

function CheckBucketIcon({ bucket }: { bucket: PrCheckBucket }) {
  switch (bucket) {
    case "fail":
      return (
        <XCircleIcon
          size={14}
          weight="fill"
          className="shrink-0 text-(--red-9)"
        />
      );
    case "cancel":
      return <ProhibitIcon size={14} className="shrink-0 text-(--gray-9)" />;
    case "pending":
      return (
        <CircleNotchIcon
          size={14}
          className="shrink-0 animate-spin text-(--amber-9)"
        />
      );
    case "pass":
      return (
        <CheckCircleIcon
          size={14}
          weight="fill"
          className="shrink-0 text-(--green-9)"
        />
      );
    case "skipping":
      return <MinusCircleIcon size={14} className="shrink-0 text-(--gray-8)" />;
  }
}
