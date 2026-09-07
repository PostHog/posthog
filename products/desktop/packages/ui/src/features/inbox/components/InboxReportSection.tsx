import { CaretDownIcon } from "@phosphor-icons/react";
import { Button, Spinner } from "@posthog/quill";
import type { SignalReport } from "@posthog/shared/types";
import type { ReactNode } from "react";
import { useState } from "react";

const SECTION_PREVIEW_LIMIT = 5;

export interface InboxReportSectionProps {
  title: string;
  reports: SignalReport[];
  count: number;
  emptyNote?: string;
  defaultOpen?: boolean;
  isLoading?: boolean;
  renderReport: (report: SignalReport) => ReactNode;
  onShowMore?: () => void;
  onOpenChange?: (open: boolean) => void;
}

export function InboxReportSection({
  title,
  reports,
  count,
  emptyNote,
  defaultOpen = true,
  isLoading = false,
  renderReport,
  onShowMore,
  onOpenChange,
}: InboxReportSectionProps): React.JSX.Element | null {
  const [open, setOpen] = useState(defaultOpen);
  const [visibleCount, setVisibleCount] = useState(SECTION_PREVIEW_LIMIT);
  if (count === 0 && reports.length === 0 && !emptyNote) return null;

  const visible = reports.slice(0, visibleCount);
  const hidden = reports.length - visible.length;

  return (
    <section className="flex flex-col gap-2">
      <button
        type="button"
        className="flex w-full cursor-pointer items-center gap-2 rounded px-0.5 py-1 text-left"
        onClick={() =>
          setOpen((current) => {
            const next = !current;
            onOpenChange?.(next);
            return next;
          })
        }
        aria-expanded={open}
      >
        <span className="flex items-center gap-1 font-mono font-semibold text-[11px] text-gray-10 uppercase tracking-widest">
          {title}
          <span className="tabular-nums">({count})</span>
        </span>
        <div className="h-px flex-1 bg-(--gray-5)" />
        <CaretDownIcon
          size={12}
          className={`text-gray-9 transition-transform ${open ? "rotate-180" : ""}`}
        />
      </button>
      {open &&
        (isLoading ? (
          <div className="flex justify-center py-3">
            <Spinner />
          </div>
        ) : reports.length === 0 ? (
          <p className="px-1 py-2 text-[13.5px] text-gray-10">{emptyNote}</p>
        ) : (
          <div className="flex flex-col gap-1">
            {visible.map((report) => renderReport(report))}
            {hidden > 0 && (
              <Button
                type="button"
                variant="link-muted"
                size="sm"
                className="self-center text-gray-10"
                onClick={() =>
                  setVisibleCount((current) =>
                    Math.min(current + SECTION_PREVIEW_LIMIT, reports.length),
                  )
                }
              >
                Show more ({hidden})
              </Button>
            )}
            {onShowMore && hidden === 0 && count > reports.length && (
              <Button
                type="button"
                variant="link-muted"
                size="sm"
                className="self-center text-gray-10"
                onClick={() => {
                  setVisibleCount((current) =>
                    Math.min(current + SECTION_PREVIEW_LIMIT, count),
                  );
                  onShowMore();
                }}
              >
                Show more ({Math.max(0, count - reports.length)})
              </Button>
            )}
          </div>
        ))}
    </section>
  );
}
