import { CheckCircle, Clock } from "@phosphor-icons/react";
import { cn } from "@posthog/quill";

export function GithubApprovalNotice({
  state,
  className,
}: {
  state: "awaiting" | "approved";
  className?: string;
}) {
  if (state === "awaiting") {
    return (
      <div className={cn("flex flex-col gap-1", className)}>
        <div className="flex items-center gap-2 font-medium text-(--gray-12) text-sm">
          <Clock size={16} className="text-(--amber-11)" />
          Waiting for a GitHub org owner to approve
        </div>
        <span className="text-(--gray-11) text-sm">
          Cloud runs will not be available until your integration is approved.
          In the meantime, you can run tasks on your local machine.
        </span>
      </div>
    );
  }

  return (
    <div
      className={cn(
        "flex items-center gap-2 font-medium text-(--gray-12) text-sm",
        className,
      )}
    >
      <CheckCircle size={16} weight="fill" className="text-(--green-9)" />
      Your GitHub org owner approved the request
    </div>
  );
}
