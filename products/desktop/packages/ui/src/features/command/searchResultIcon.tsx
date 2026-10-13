import { GitPullRequestIcon } from "@phosphor-icons/react";
import type { Task, TaskSearchResult } from "@posthog/shared/domain-types";
import { iconForTemplate } from "@posthog/ui/features/canvas/components/canvasTemplateIcon";
import { channelGlyph } from "@posthog/ui/features/canvas/components/channelGlyph";
import { TaskCommandIcon } from "@posthog/ui/features/command/TaskCommandIcon";
import { TaskIcon } from "@posthog/ui/features/sidebar/components/items/TaskIcon";
import { FileIcon } from "@posthog/ui/primitives/FileIcon";
import { SlackMark } from "@posthog/ui/primitives/SlackMark";
import type { ReactNode } from "react";

const ICON_SIZE = 12;

function metadataString(
  result: TaskSearchResult,
  key: string,
): string | undefined {
  const value = result.metadata[key];
  return typeof value === "string" && value ? value : undefined;
}

export function searchResultIcon(
  result: TaskSearchResult,
  { title, task }: { title: string; task?: Task },
): ReactNode {
  switch (result.kind) {
    case "channel":
      return channelGlyph(title, {
        size: ICON_SIZE,
        className: "text-muted-foreground",
      });
    case "pull_request":
      return <GitPullRequestIcon size={ICON_SIZE} className="text-gray-11" />;
    case "canvas":
      return iconForTemplate(metadataString(result, "template_id") ?? "", {
        size: ICON_SIZE,
      });
    case "artifact":
      return <FileIcon filename={title} size={ICON_SIZE} />;
    default:
      if (task) return <TaskCommandIcon task={task} />;
      if (result.origin_product === "slack") return <SlackMark size={12} />;
      return (
        <TaskIcon
          workspaceMode={result.latest_run?.environment ?? undefined}
          taskRunStatus={result.latest_run?.status ?? undefined}
          originProduct={result.origin_product ?? undefined}
        />
      );
  }
}
