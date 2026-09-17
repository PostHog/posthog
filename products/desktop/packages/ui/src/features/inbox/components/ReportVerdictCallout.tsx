import type {
  ReportVerdict,
  ReportVerdictTone,
} from "@posthog/core/inbox/reportVerdict";
import { cn } from "@posthog/quill";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import type { ReactNode } from "react";

const TONE_CLASS: Record<ReportVerdictTone, string> = {
  decision: "border-(--amber-6) bg-(--amber-2)",
  danger: "border-(--red-6) bg-(--red-2)",
  progress: "border-(--gray-5) bg-(--gray-1)",
  info: "border-(--blue-6) bg-(--blue-2)",
};

export function ReportVerdictCallout({
  verdict,
  details,
  children,
}: {
  verdict: ReportVerdict;
  details?: ReactNode;
  children?: ReactNode;
}): React.JSX.Element {
  return (
    <div
      className={cn(
        "flex select-none flex-col gap-3 rounded-lg border p-4",
        TONE_CLASS[verdict.tone],
      )}
    >
      <div className="flex flex-col gap-1">
        <span className="flex items-center gap-2 font-semibold text-[15px] text-gray-12">
          {verdict.tone === "progress" && <Spinner />}
          {verdict.title}
        </span>
        <span className="text-[14px] text-gray-11">{verdict.body}</span>
        {details}
      </div>
      {children}
    </div>
  );
}
