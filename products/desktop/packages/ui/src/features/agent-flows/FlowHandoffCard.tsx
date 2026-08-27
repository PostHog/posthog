import { FileTextIcon } from "@phosphor-icons/react";
import type { AgentFlowHandoff } from "@posthog/shared";
import { usePanelLayoutStore } from "@posthog/ui/features/panels/panelLayoutStore";
import { useSessionTaskId } from "@posthog/ui/features/sessions/useSessionTaskId";
import { useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { useFlowHandoffArtifact } from "./useFlowHandoffArtifact";

const SUMMARY_CAP = 120;

function summarize(markdown: string): string {
  const line = markdown
    .split("\n")
    .map((raw) => raw.replace(/^[#>\-*\s]+/, "").trim())
    .find((raw) => raw.length > 0);
  if (!line) {
    return "Handoff document";
  }
  const plain = line.replace(/[*`_]/g, "");
  return plain.length > SUMMARY_CAP ? `${plain.slice(0, SUMMARY_CAP)}…` : plain;
}

/**
 * The chat row for a handoff: a link to the document, not the document. The
 * text only unfolds here when the document could not be stored.
 */
export function FlowHandoffCard({
  handoff,
  fallbackText,
}: {
  handoff: AgentFlowHandoff | null;
  fallbackText?: string;
}) {
  const taskId = useSessionTaskId();
  const openArtifactTab = usePanelLayoutStore((state) => state.openArtifactTab);
  const artifact = useFlowHandoffArtifact(taskId, handoff);
  const [expanded, setExpanded] = useState(false);

  const markdown = handoff?.markdown ?? fallbackText ?? "";
  const stored = artifact.data;
  const canOpen = !!taskId && !!handoff && !!stored;

  const action = canOpen
    ? "Open"
    : artifact.isPending
      ? "Saving"
      : expanded
        ? "Hide"
        : "Show";

  return (
    <div className="flex max-w-3xl flex-col gap-1">
      <button
        type="button"
        className="flex items-center gap-2.5 rounded-md border border-gray-5 bg-gray-1 px-2.5 py-2 text-left transition-colors hover:bg-gray-3"
        onClick={() => {
          if (canOpen && taskId && handoff && stored) {
            openArtifactTab(taskId, {
              runId: stored.runId,
              artifactId: stored.artifactId,
              name: handoff.artifactName,
            });
            return;
          }
          setExpanded((current) => !current);
        }}
      >
        <FileTextIcon size={16} className="shrink-0 text-gray-10" />
        <span className="flex min-w-0 flex-col">
          <span className="truncate font-medium text-[13px] text-gray-12">
            {handoff?.title ?? "Handoff"}
            {handoff && handoff.version > 1 ? (
              <span className="ml-1.5 text-gray-10">v{handoff.version}</span>
            ) : null}
          </span>
          <span className="truncate text-[12px] text-gray-10">
            {summarize(markdown)}
          </span>
        </span>
        <span className="ml-auto shrink-0 pl-2 text-[12px] text-gray-10">
          {action}
        </span>
      </button>
      {expanded && !canOpen && markdown ? (
        <div className="chat-markdown max-h-[40vh] overflow-y-auto rounded-md border border-gray-4 bg-gray-1 px-3 py-2 text-[13px] text-gray-12">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
        </div>
      ) : null}
    </div>
  );
}
