/**
 * Consistent TUI rendering for `background-job` custom messages, regardless
 * of which extension (`subagent`, `workflow`, ...) started the job.
 */

import type { ImageContent, TextContent } from "@earendil-works/pi-ai";
import type { MessageRenderer } from "@earendil-works/pi-coding-agent";
import { getMarkdownTheme } from "@earendil-works/pi-coding-agent";
import { Markdown } from "@earendil-works/pi-tui";
import type { BackgroundJobDetails } from "./jobs";

function statusColor(
  status: BackgroundJobDetails["status"],
): "success" | "error" | "muted" {
  switch (status) {
    case "completed":
      return "success";
    case "failed":
      return "error";
    case "cancelled":
      return "muted";
  }
}

export const renderBackgroundJobMessage: MessageRenderer<
  BackgroundJobDetails
> = (message, _options, theme) => {
  const status = message.details?.status ?? "completed";
  const text =
    typeof message.content === "string"
      ? message.content
      : message.content
          .map((part: TextContent | ImageContent) =>
            part.type === "text" ? part.text : "",
          )
          .join("");
  return new Markdown(text, 0, 0, getMarkdownTheme(), {
    color: (part) => theme.fg(statusColor(status), part),
  });
};
