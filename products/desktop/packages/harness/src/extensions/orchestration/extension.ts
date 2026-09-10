import type {
  ExtensionAPI,
  ExtensionContext,
  ExtensionFactory,
  Theme,
} from "@earendil-works/pi-coding-agent";
import type { Component, TUI } from "@earendil-works/pi-tui";
import { resolveOrchestrationResource } from "./resources";
import { registerSubagentTool } from "./tools/subagent-tool";
import { registerWorkflowTool } from "./tools/workflow-tool";
import { OrchestrationStatusEditor } from "./ui/status-editor";
import { renderOrchestrationFooterLines } from "./ui/status-footer";
import {
  hasActiveAgentRuns,
  hasActiveWorkflows,
  subscribeToOrchestration,
} from "./ui/status-registry";
import { showSubagentStatusOverlay } from "./ui/subagent-status-overlay";
import { showWorkflowStatusOverlay } from "./ui/workflow-status-overlay";

export function createOrchestrationExtension(): ExtensionFactory {
  return (pi: ExtensionAPI) => {
    let activeTui: TUI | undefined;
    let footerInstalled = false;
    let spinnerFrame = 0;
    let currentContext: ExtensionContext | undefined;
    let unsubscribe: (() => void) | undefined;
    let spinnerTimer: ReturnType<typeof setInterval> | undefined;

    const footerFactory = (
      tui: TUI,
      theme: Theme,
    ): Component & { dispose?(): void } => {
      activeTui = tui;
      return {
        invalidate() {},
        render: (width: number) =>
          renderOrchestrationFooterLines(theme, width, spinnerFrame),
      };
    };

    const syncFooter = () => {
      if (!currentContext) {
        return;
      }
      const hasActiveRuns = hasActiveAgentRuns() || hasActiveWorkflows();
      if (hasActiveRuns === footerInstalled) {
        return;
      }
      footerInstalled = hasActiveRuns;
      currentContext.ui.setFooter(hasActiveRuns ? footerFactory : undefined);
    };

    const refreshStatus = () => {
      activeTui?.requestRender();
      syncFooter();
    };

    const startStatusUpdates = () => {
      unsubscribe ??= subscribeToOrchestration(refreshStatus);
      spinnerTimer ??= setInterval(() => {
        if (!hasActiveAgentRuns() && !hasActiveWorkflows()) {
          return;
        }
        spinnerFrame++;
        activeTui?.requestRender();
      }, 150);
    };

    const stopStatusUpdates = () => {
      if (spinnerTimer) {
        clearInterval(spinnerTimer);
        spinnerTimer = undefined;
      }
      unsubscribe?.();
      unsubscribe = undefined;
      activeTui = undefined;
    };

    pi.on("session_start", (_event, context) => {
      currentContext = context;
      footerInstalled = false;
      startStatusUpdates();
      syncFooter();

      context.ui.setEditorComponent(
        (tui, theme, keybindings) =>
          new OrchestrationStatusEditor(
            tui,
            theme,
            keybindings,
            (workflowId) => {
              if (workflowId) {
                void showWorkflowStatusOverlay(context, workflowId);
              } else {
                void showSubagentStatusOverlay(context);
              }
            },
          ),
      );
    });

    pi.on("session_shutdown", () => {
      stopStatusUpdates();
      currentContext = undefined;
      footerInstalled = false;
    });

    pi.on("resources_discover", () => ({
      skillPaths: [resolveOrchestrationResource("skills")],
    }));

    registerSubagentTool(pi);
    registerWorkflowTool(pi);
  };
}

export default createOrchestrationExtension();
