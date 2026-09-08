import type {
  AppBridge,
  McpUiDisplayMode,
} from "@modelcontextprotocol/ext-apps/app-bridge";
import type {
  CallToolResult,
  ReadResourceResult,
  Tool,
} from "@modelcontextprotocol/sdk/types.js";
import { ArrowsIn, ArrowsOut, Plugs, X } from "@phosphor-icons/react";
import { useService } from "@posthog/di/react";
import { useHostTRPC } from "@posthog/host-router/react";
import { Button, Text } from "@posthog/quill";
import type { ToolViewProps } from "@posthog/ui/features/sessions/components/session-update/toolCallUtils";
import { logger } from "@posthog/ui/shell/logger";
import { useThemeStore } from "@posthog/ui/shell/themeStore";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useSubscription } from "@trpc/tanstack-react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { type Phase, useAppBridge } from "../hooks/useAppBridge";
import {
  MCP_SANDBOX_PROXY_URL,
  type McpSandboxProxyUrlProvider,
} from "../identifiers";
import {
  isMcpAppEventForToolCall,
  sendToolResultOnce,
} from "../utils/mcp-app-host-utils";

const log = logger.scope("mcp-app-host");

interface McpAppHostProps extends ToolViewProps {
  mcpToolName: string;
  serverName: string;
  toolName: string;
  resourceUri?: string;
}

export function McpAppHost({
  toolCall,
  mcpToolName,
  serverName,
  toolName,
  resourceUri,
}: McpAppHostProps) {
  const trpc = useHostTRPC();
  const getSandboxProxyUrl = useService<McpSandboxProxyUrlProvider>(
    MCP_SANDBOX_PROXY_URL,
  );
  const sandboxProxyUrl = useMemo(
    () => getSandboxProxyUrl(),
    [getSandboxProxyUrl],
  );
  const containerRef = useRef<HTMLDivElement>(null);
  const [, setPhase] = useState<Phase>("loading");
  const [displayMode, setDisplayMode] = useState<McpUiDisplayMode>("inline");
  const [iframeHeight, setIframeHeight] = useState(300);
  const [containerWidth, setContainerWidth] = useState(640);
  const [iframeEl, setIframeEl] = useState<HTMLIFrameElement | null>(null);
  const isDarkMode = useThemeStore((s) => s.isDarkMode);

  const { data: uiResource, isLoading: resourceLoading } = useQuery(
    resourceUri
      ? trpc.mcpApps.getUiResourceByUri.queryOptions(
          { serverName, resourceUri },
          { staleTime: Number.POSITIVE_INFINITY },
        )
      : trpc.mcpApps.getUiResource.queryOptions(
          { toolKey: mcpToolName },
          { staleTime: Number.POSITIVE_INFINITY },
        ),
  );

  const { data: toolDefinition } = useQuery(
    trpc.mcpApps.getToolDefinition.queryOptions(
      { toolKey: mcpToolName },
      { staleTime: Number.POSITIVE_INFINITY },
    ),
  );

  useEffect(() => {
    log.info("McpAppHost render", {
      mcpToolName,
      selectedResourceUri: resourceUri,
      toolCallId: toolCall.toolCallId,
      status: toolCall.status,
      resourceLoading,
      hasResource: !!uiResource,
      resourceUri: uiResource?.uri,
    });
  }, [
    mcpToolName,
    resourceUri,
    toolCall.toolCallId,
    toolCall.status,
    resourceLoading,
    uiResource,
    uiResource?.uri,
  ]);

  const proxyToolCallMut = useMutation(
    trpc.mcpApps.proxyToolCall.mutationOptions(),
  );
  const proxyResourceReadMut = useMutation(
    trpc.mcpApps.proxyResourceRead.mutationOptions(),
  );
  const openLinkMut = useMutation(trpc.mcpApps.openLink.mutationOptions());

  const deliveredResultsRef = useRef(new WeakMap<object, Set<string>>());
  const deliverResult = useCallback(
    (bridge: AppBridge, rawOutput: unknown) => {
      if (
        sendToolResultOnce(
          deliveredResultsRef.current,
          bridge,
          toolCall.toolCallId,
          rawOutput,
        )
      ) {
        log.info("Sending tool result to app", {
          mcpToolName,
          toolCallId: toolCall.toolCallId,
        });
      }
    },
    [mcpToolName, toolCall.toolCallId],
  );
  const replayCompletedResult = useCallback(
    (bridge: AppBridge) => {
      if (toolCall.status !== "completed" && toolCall.status !== "failed") {
        return;
      }
      if (toolCall.rawOutput == null) return;
      deliverResult(bridge, toolCall.rawOutput);
    },
    [deliverResult, toolCall.rawOutput, toolCall.status],
  );

  const { sendWhenReady } = useAppBridge({
    iframeEl,
    uiResource: uiResource,
    serverName,
    toolName,
    toolDefinition: toolDefinition as Tool | null | undefined,
    toolCall,
    isDarkMode,
    displayMode,
    containerWidth,
    onPhaseChange: setPhase,
    onSizeChange: setIframeHeight,
    onDisplayModeChange: setDisplayMode,
    onBridgeInitialized: replayCompletedResult,
    proxyToolCall: proxyToolCallMut.mutateAsync as (args: {
      serverName: string;
      toolName: string;
      args?: Record<string, unknown>;
    }) => Promise<CallToolResult>,
    proxyResourceRead: proxyResourceReadMut.mutateAsync as (args: {
      serverName: string;
      uri: string;
    }) => Promise<ReadResourceResult>,
    openLink: openLinkMut.mutateAsync,
  });

  useSubscription(
    trpc.mcpApps.onToolResult.subscriptionOptions(
      { toolKey: mcpToolName },
      {
        onData: (event) => {
          if (!isMcpAppEventForToolCall(event, toolCall.toolCallId)) return;
          sendWhenReady((bridge) => deliverResult(bridge, event.result));
        },
      },
    ),
  );

  useEffect(() => {
    if (toolCall.status !== "completed" && toolCall.status !== "failed") return;
    if (toolCall.rawOutput == null) return;
    sendWhenReady((bridge) => deliverResult(bridge, toolCall.rawOutput));
  }, [deliverResult, sendWhenReady, toolCall.rawOutput, toolCall.status]);

  useSubscription(
    trpc.mcpApps.onToolCancelled.subscriptionOptions(
      { toolKey: mcpToolName },
      {
        onData: (event) => {
          if (!isMcpAppEventForToolCall(event, toolCall.toolCallId)) return;
          log.info("Received tool cancellation from subscription", {
            mcpToolName,
            toolCallId: toolCall.toolCallId,
          });
          sendWhenReady((bridge) => bridge.sendToolCancelled({}));
        },
      },
    ),
  );

  // Track inline container width with ResizeObserver
  useEffect(() => {
    if (displayMode !== "inline") return;
    const el = containerRef.current;
    if (!el) return;
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setContainerWidth(Math.round(entry.contentRect.width));
      }
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [displayMode]);

  // Handle escape key for fullscreen
  useEffect(() => {
    if (displayMode !== "fullscreen") return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setDisplayMode("inline");
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [displayMode]);

  if (resourceLoading || !uiResource) {
    return null;
  }

  const iframeElement = (
    <iframe
      key={`${uiResource.serverName}\n${uiResource.uri}`}
      ref={setIframeEl}
      src={sandboxProxyUrl}
      // allow-same-origin would resolve this frame to the host's own origin.
      sandbox="allow-scripts allow-forms allow-presentation"
      style={{
        height: displayMode === "fullscreen" ? "100%" : `${iframeHeight}px`,
      }}
      title={`MCP App: ${serverName} - ${toolName}`}
      className="w-full rounded-(--radius-2) border-0"
    />
  );

  const fullscreenToggle = (
    <div className="flex justify-end py-0.5">
      <Button
        size="icon-xs"
        variant="default"
        onClick={(event) => {
          event.stopPropagation();
          const newMode = displayMode === "inline" ? "fullscreen" : "inline";
          setDisplayMode(newMode);
        }}
        title={
          displayMode === "inline" ? "Expand to fullscreen" : "Exit fullscreen"
        }
      >
        {displayMode === "inline" ? <ArrowsOut /> : <ArrowsIn />}
      </Button>
    </div>
  );

  if (displayMode === "fullscreen") {
    const portalTarget = document.getElementById("fullscreen-portal");
    if (portalTarget) {
      return (
        <>
          {fullscreenToggle}

          {createPortal(
            <div className="pointer-events-auto absolute inset-0 flex flex-col bg-gray-1 transition-opacity duration-150">
              <div className="flex items-center justify-between border-gray-6 border-b px-4 py-2">
                <div className="flex items-center gap-2">
                  <Plugs size={14} className="text-gray-11" />
                  <Text render={<span />} size="sm" className="text-gray-11">
                    {serverName} - {toolName}
                  </Text>
                </div>
                <Button
                  size="icon-xs"
                  variant="default"
                  onClick={() => {
                    setDisplayMode("inline");
                  }}
                  title="Exit fullscreen (Escape)"
                >
                  <X />
                </Button>
              </div>

              <div className="flex-1 overflow-hidden p-4">{iframeElement}</div>
            </div>,
            portalTarget,
          )}
        </>
      );
    }
  }

  return (
    <div>
      {fullscreenToggle}
      <div
        ref={containerRef}
        className="overflow-hidden rounded-lg border border-gray-6"
      >
        {iframeElement}
      </div>
    </div>
  );
}
