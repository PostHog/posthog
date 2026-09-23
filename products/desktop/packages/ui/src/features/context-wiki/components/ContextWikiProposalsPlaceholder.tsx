import { FileTextIcon, WarningCircleIcon } from "@phosphor-icons/react";
import {
  Button,
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@posthog/quill";
import type { ReactElement } from "react";

type Props =
  | { state: "empty" | "unselected" }
  | { state: "error"; onRetry: () => void; retrying: boolean };

export function ContextWikiProposalsPlaceholder(props: Props): ReactElement {
  const content = {
    empty: {
      title: "No suggested edits",
      description: "Ask a task to propose a correction to a shared wiki page.",
    },
    unselected: {
      title: "Review a suggested edit",
      description: "Select an edit to review its changes.",
    },
    error: {
      title: "Could not load suggested edits",
      description: "Try again to load your suggested wiki edits.",
    },
  }[props.state];
  return (
    <Empty
      className="min-w-0 flex-1"
      role={props.state === "error" ? "alert" : undefined}
    >
      <EmptyHeader>
        <EmptyMedia variant="icon">
          {props.state === "error" ? <WarningCircleIcon /> : <FileTextIcon />}
        </EmptyMedia>
        <EmptyTitle>{content.title}</EmptyTitle>
        <EmptyDescription>{content.description}</EmptyDescription>
      </EmptyHeader>
      {props.state === "error" && (
        <EmptyContent>
          <Button
            variant="outline"
            size="default"
            onClick={props.onRetry}
            disabled={props.retrying}
            loading={props.retrying}
          >
            Try again
          </Button>
        </EmptyContent>
      )}
    </Empty>
  );
}
