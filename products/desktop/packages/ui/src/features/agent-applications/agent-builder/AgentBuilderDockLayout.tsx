import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { type ReactNode, useEffect } from "react";
import { Panel, PanelGroup, PanelResizeHandle } from "react-resizable-panels";
import { AGENT_PLATFORM_FLAG } from "../featureFlag";
import { AgentBuilderDock } from "./AgentBuilderDock";
import { useAgentBuilderStore } from "./agentBuilderStore";

/**
 * Wraps the `/code/agents` content in a resizable split with the always-on
 * agent builder dock pinned right. Gated behind the `agent-platform` flag — when
 * disabled, the content renders unchanged with no dock or affordance. Hidden by
 * default; toggled via the edge affordance, the dock's hide button, or
 * Cmd/Ctrl+I. Panel sizes persist (`autoSaveId`).
 *
 * The content panel is always mounted in the same tree position; only the dock
 * panel + resize handle toggle. Keeping the content's React identity stable
 * across show/hide means panes don't remount — so per-pane state (the memory
 * file you had open, a sessions filter, scroll position) survives toggling.
 */
export function AgentBuilderDockLayout({ children }: { children: ReactNode }) {
  const enabled = useFeatureFlag(AGENT_PLATFORM_FLAG);
  const visible = useAgentBuilderStore((s) => s.visible);
  const toggleVisible = useAgentBuilderStore((s) => s.toggleVisible);

  useEffect(() => {
    if (!enabled) return;
    const onKey = (e: KeyboardEvent) => {
      // Cmd/Ctrl+Shift+I — Cmd+I alone is taken by the inbox.
      if (!(e.metaKey || e.ctrlKey) || e.altKey || !e.shiftKey) return;
      if (e.key.toLowerCase() !== "i") return;
      const t = e.target as HTMLElement | null;
      if (
        t?.tagName === "INPUT" ||
        t?.tagName === "TEXTAREA" ||
        t?.isContentEditable
      ) {
        return;
      }
      e.preventDefault();
      toggleVisible();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [enabled, toggleVisible]);

  // Flag off → no agent builder anywhere in /code/agents.
  if (!enabled) {
    return <>{children}</>;
  }

  // The content panel stays mounted whether the dock is open or not; only the
  // dock panel + handle render conditionally. The open affordance lives in the
  // agents page headers (AgentBuilderHeaderControls); Cmd/Ctrl+Shift+I toggles.
  return (
    <PanelGroup
      direction="horizontal"
      autoSaveId="agents-agent-builder-dock"
      className="h-full min-h-0"
    >
      <Panel
        id="agents-content"
        order={1}
        defaultSize={68}
        minSize={40}
        className="flex min-h-0 flex-col"
      >
        {children}
      </Panel>
      {visible ? (
        <>
          <PanelResizeHandle className="w-px bg-(--gray-5) transition-colors hover:bg-(--gray-7) data-[resize-handle-state=drag]:bg-(--accent-9)" />
          <Panel
            id="agents-dock"
            order={2}
            defaultSize={32}
            minSize={22}
            maxSize={48}
            className="flex min-h-0 flex-col"
          >
            <AgentBuilderDock />
          </Panel>
        </>
      ) : null}
    </PanelGroup>
  );
}
