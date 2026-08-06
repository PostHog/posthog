import { Skeleton } from "@posthog/quill";

/**
 * Loading state for inbox detail screens, mirroring InboxDetailFrame's
 * header + two-column body so a cold deep-link open doesn't jump from a
 * centered spinner to the real layout.
 */
export function InboxDetailSkeleton() {
  return (
    <div className="flex min-h-full flex-col" aria-hidden>
      <div className="flex flex-col gap-3 border-(--gray-5) border-b px-6 pt-5 pb-5">
        <Skeleton className="h-3 w-28" />
        <div className="flex items-center gap-2.5">
          <Skeleton className="h-6 w-[45%] max-w-96" />
          <Skeleton className="h-5 w-10" />
          <Skeleton className="h-5 w-20" />
        </div>
        <Skeleton className="h-3 w-52" />
      </div>
      <div className="@container mx-auto w-full max-w-[calc(160ch+5rem)] px-6 py-5">
        <div className="grid @4xl:grid-cols-[minmax(0,80ch)_minmax(0,1fr)] grid-cols-1 gap-5">
          <div className="flex min-w-0 flex-col gap-5">
            <Skeleton className="h-4 w-32" />
            <div className="flex flex-col gap-2">
              <Skeleton className="h-3.5 w-[92%]" />
              <Skeleton className="h-3.5 w-[85%]" />
              <Skeleton className="h-3.5 w-[95%]" />
              <Skeleton className="h-3.5 w-[60%]" />
            </div>
            <div className="flex flex-col gap-2">
              <Skeleton className="h-3.5 w-[88%]" />
              <Skeleton className="h-3.5 w-[70%]" />
            </div>
          </div>
          <div className="flex min-w-0 flex-col gap-5">
            <Skeleton className="h-4 w-24" />
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-20 w-full" />
          </div>
        </div>
      </div>
    </div>
  );
}
