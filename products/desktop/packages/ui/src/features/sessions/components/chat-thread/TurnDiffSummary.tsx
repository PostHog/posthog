import { GitDiff } from "@phosphor-icons/react";
import { extractCloudToolFileDiffs } from "@posthog/core/task-detail/cloudToolChanges";
import type { TurnContext } from "@posthog/ui/features/sessions/components/buildConversationItems";
import { CodePreview } from "@posthog/ui/features/sessions/components/session-update/CodePreview";
import { ToolRow } from "@posthog/ui/features/sessions/components/session-update/ToolRow";
import { useMemo } from "react";

interface TurnDiffSummaryProps {
  toolCalls: TurnContext["toolCalls"];
  turnId: string;
}

export function TurnDiffSummary({ toolCalls, turnId }: TurnDiffSummaryProps) {
  const diffs = useMemo(
    () => extractCloudToolFileDiffs(toolCalls),
    [toolCalls],
  );

  if (diffs.length === 0) return null;

  const linesAdded = diffs.reduce(
    (total, diff) => total + (diff.linesAdded ?? 0),
    0,
  );
  const linesRemoved = diffs.reduce(
    (total, diff) => total + (diff.linesRemoved ?? 0),
    0,
  );
  const fileLabel =
    diffs.length === 1 ? "1 file changed" : `${diffs.length} files changed`;

  return (
    <ToolRow
      icon={GitDiff}
      defaultOpen={false}
      boxed={false}
      content={
        <div className="flex flex-col gap-3">
          {diffs.map((diff) => (
            <CodePreview
              key={diff.path}
              content={diff.newText ?? ""}
              filePath={diff.path}
              showPath
              oldContent={diff.oldText ?? ""}
              maxHeight="500px"
              cacheKey={`${turnId}:${diff.path}`}
            />
          ))}
        </div>
      }
    >
      <span>{fileLabel}</span>
      <span className="font-mono text-green-11 text-xs">+{linesAdded}</span>
      <span className="font-mono text-red-11 text-xs">-{linesRemoved}</span>
    </ToolRow>
  );
}
