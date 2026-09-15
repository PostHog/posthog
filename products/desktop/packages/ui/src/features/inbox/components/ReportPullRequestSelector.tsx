import { parsePrUrl } from "@posthog/core/inbox/reportPresentation";
import type { ReportPullRequest } from "@posthog/core/inbox/reportPullRequests";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@posthog/quill";

export interface ReportPullRequestSelectorProps {
  pullRequests: readonly ReportPullRequest[];
  value: string;
  onValueChange: (value: string | null) => void;
}

function pullRequestLabel(url: string): string {
  const ref = parsePrUrl(url);
  return ref ? `${ref.repoSlug}#${ref.number}` : url;
}

export function ReportPullRequestSelector({
  pullRequests,
  value,
  onValueChange,
}: ReportPullRequestSelectorProps) {
  const selected = pullRequests.find((pr) => pr.url === value);
  return (
    <Select value={value} onValueChange={onValueChange}>
      <SelectTrigger
        aria-label="Pull request"
        data-attr="inbox-report-select-pull-request"
        className="min-w-0 max-w-full"
      >
        <SelectValue className="truncate">
          {pullRequestLabel(value)} ({selected?.state})
        </SelectValue>
      </SelectTrigger>
      <SelectContent>
        {pullRequests.map((pr) => (
          <SelectItem key={pr.url} value={pr.url}>
            {pullRequestLabel(pr.url)} ({pr.state})
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
