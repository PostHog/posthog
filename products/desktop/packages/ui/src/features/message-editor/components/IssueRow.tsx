import { githubIssueStateColor } from "@posthog/core/message-editor/githubIssueChip";
import {
  Item,
  ItemContent,
  ItemDescription,
  ItemMedia,
  ItemTitle,
} from "@posthog/quill";
import type { GithubRefKind, GithubRefState } from "../types";

export interface IssueRowData {
  kind: GithubRefKind;
  number: number;
  title: string;
  state: GithubRefState;
  repo: string;
  labels: string[];
  isDraft?: boolean;
}

function refStateLabel(ref: IssueRowData): string {
  if (ref.kind === "pr" && ref.isDraft && ref.state === "OPEN") return "Draft";
  return ref.state.charAt(0) + ref.state.slice(1).toLowerCase();
}

export function IssueRow({ issue }: { issue: IssueRowData }) {
  const kindLabel = issue.kind === "pr" ? "Pull request" : "Issue";
  return (
    <Item size="xs" className="border-0 p-0">
      <ItemMedia variant="icon" className="mt-1 self-start">
        <span
          aria-hidden="true"
          className="inline-block h-2.5 w-2.5 rounded-full"
          style={{ background: githubIssueStateColor(issue.state) }}
        />
      </ItemMedia>
      <ItemContent variant="menuItem">
        <ItemTitle className="whitespace-normal text-left">
          #{issue.number} - {issue.title}
        </ItemTitle>
        <ItemDescription className="text-left">
          {kindLabel} · {refStateLabel(issue)} · {issue.repo}
          {issue.labels.length > 0 && ` · ${issue.labels.join(", ")}`}
        </ItemDescription>
      </ItemContent>
    </Item>
  );
}
