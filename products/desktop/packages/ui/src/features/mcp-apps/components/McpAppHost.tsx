import type { McpUiDisplayMode } from "@modelcontextprotocol/ext-apps/app-bridge";
import type {
  CallToolResult,
  ReadResourceResult,
  Tool,
} from "@modelcontextprotocol/sdk/types.js";
import { ArrowsIn, ArrowsOut, Plugs, X } from "@phosphor-icons/react";
import {
  POSTHOG_EXEC_TOOL_KEY,
  resolveResultResourceUri,
} from "@posthog/core/mcp-apps/schemas";
import { useService } from "@posthog/di/react";
import { useHostTRPC } from "@posthog/host-router/react";
import type { ToolViewProps } from "@posthog/ui/features/sessions/components/session-update/toolCallUtils";
import { logger } from "@posthog/ui/shell/logger";
import { useThemeStore } from "@posthog/ui/shell/themeStore";
import { Box, Flex, IconButton, Text } from "@radix-ui/themes";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useSubscription } from "@trpc/tanstack-react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { type Phase, useAppBridge } from "../hooks/useAppBridge";
import {
  MCP_SANDBOX_PROXY_URL,
  type McpSandboxProxyUrlProvider,
} from "../identifiers";
import { toCallToolResult } from "../utils/mcp-app-host-utils";

const log = logger.scope("mcp-app-host");

interface McpAppHostProps extends ToolViewProps {
  mcpToolName: string;
  serverName: string;
  toolName: string;
}

export function McpAppHost({
  toolCall,
  mcpToolName,
  serverName,
  toolName,
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
  const [_phase, setPhase] = useState<Phase>("loading");
  const [displayMode, setDisplayMode] = useState<McpUiDisplayMode>("inline");
  const [iframeHeight, setIframeHeight] = useState(300);
  const [containerWidth, setContainerWidth] = useState(640);
  const [iframeEl, setIframeEl] = useState<HTMLIFrameElement | null>(null);
  const isDarkMode = useThemeStore((s) => s.isDarkMode);

  const isExec = mcpToolName === POSTHOG_EXEC_TOOL_KEY;
  const execResourceUri = isExec
    ? resolveResultResourceUri(toolCall.rawOutput)
    : undefined;

  const { data: uiResource, isLoading: resourceLoading } = useQuery(
    isExec
      ? trpc.mcpApps.getUiResourceByUri.queryOptions(
          { serverName, resourceUri: execResourceUri ?? "" },
          { staleTime: Number.POSITIVE_INFINITY, enabled: !!execResourceUri },
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
      isExec,
      toolCallId: toolCall.toolCallId,
      status: toolCall.status,
      resourceLoading,
      hasResource: !!uiResource,
      resourceUri: uiResource?.uri,
    });
  }, [
    mcpToolName,
    isExec,
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

  const sentResultForCallRef = useRef<string | null>(null);
  const sendResultOnce = useCallback(
    (raw: unknown) => {
      if (sentResultForCallRef.current === toolCall.toolCallId) return;
      sentResultForCallRef.current = toolCall.toolCallId;
      const toolResult = toCallToolResult(raw);
      log.info("Sending tool result to app", { mcpToolName, toolResult });
      sendWhenReady((bridge) => bridge.sendToolResult(toolResult));
    },
    [toolCall.toolCallId, sendWhenReady, mcpToolName],
  );

  // Forward tool results from subscriptions
  useSubscription(
    trpc.mcpApps.onToolResult.subscriptionOptions(
      { toolKey: mcpToolName },
      {
        onData: (event) => {
          if (isExec) {
            if (event.toolCallId !== toolCall.toolCallId) return;
            sendResultOnce(event.result);
            return;
          }
          const toolResult = toCallToolResult(event.result);
          log.info("Sending tool result to app", {
            mcpToolName,
            toolResult,
          });

          sendWhenReady((bridge) => bridge.sendToolResult(toolResult));
        },
      },
    ),
  );

  useEffect(() => {
    if (!isExec) return;
    if (toolCall.status !== "completed" && toolCall.status !== "failed") return;
    if (toolCall.rawOutput == null) {
      log.info("exec replay skipped: no rawOutput on toolCall", {
        toolCallId: toolCall.toolCallId,
        status: toolCall.status,
      });
      return;
    }
    log.info("exec replay: sending result from toolCall prop", {
      toolCallId: toolCall.toolCallId,
    });
    sendResultOnce(toolCall.rawOutput);
  }, [
    isExec,
    toolCall.status,
    toolCall.rawOutput,
    toolCall.toolCallId,
    sendResultOnce,
  ]);

  // Forward tool cancellations from subscriptions
  useSubscription(
    trpc.mcpApps.onToolCancelled.subscriptionOptions(
      { toolKey: mcpToolName },
      {
        onData: () => {
          log.info("Received tool cancellation from subscription", {
            mcpToolName,
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
      ref={setIframeEl}
      src={sandboxProxyUrl}
      // No allow-popups: app JS is same-origin with the proxy realm, so popup
      // permission here would let it window.open() past the sandbox. Apps
      // open links via ui/open-link, which the host scheme-validates.
      sandbox="allow-scripts allow-same-origin allow-forms allow-presentation"
      style={{
        height: displayMode === "fullscreen" ? "100%" : `${iframeHeight}px`,
      }}
      title={`MCP App: ${serverName} - ${toolName}`}
      className="w-full rounded-(--radius-2) border-0"
    />
  );

  const fullscreenToggle = (
    <Flex justify="end" className="py-0.5">
      <IconButton
        size="1"
        variant="ghost"
        color="gray"
        onClick={(e) => {
          e.stopPropagation();
          const newMode = displayMode === "inline" ? "fullscreen" : "inline";
          setDisplayMode(newMode);
        }}
        title={
          displayMode === "inline" ? "Expand to fullscreen" : "Exit fullscreen"
        }
      >
        {displayMode === "inline" ? (
          <ArrowsOut size={12} />
        ) : (
          <ArrowsIn size={12} />
        )}
      </IconButton>
    </Flex>
  );

  if (displayMode === "fullscreen") {
    const portalTarget = document.getElementById("fullscreen-portal");
    if (portalTarget) {
      return (
        <>
          {fullscreenToggle}

          {createPortal(
            <Box
              className="pointer-events-auto absolute inset-0 flex flex-col bg-gray-1"
              style={{
                transition: "opacity 150ms ease",
              }}
            >
              <Flex
                align="center"
                justify="between"
                className="border-gray-6 border-b px-4 py-2"
              >
                <Flex align="center" gap="2">
                  <Plugs size={14} className="text-gray-11" />
                  <Text className="text-gray-11 text-sm">
                    {serverName} - {toolName}
                  </Text>
                </Flex>
                <IconButton
                  size="1"
                  variant="ghost"
                  color="gray"
                  onClick={() => {
                    setDisplayMode("inline");
                  }}
                  title="Exit fullscreen (Escape)"
                >
                  <X size={14} />
                </IconButton>
              </Flex>

              <Box className="flex-1 overflow-hidden p-4">{iframeElement}</Box>
            </Box>,
            portalTarget,
          )}
        </>
      );
    }
  }

  return (
    <Box>
      {fullscreenToggle}
      <Box
        ref={containerRef}
        className="overflow-hidden rounded-lg border border-gray-6"
      >
        {iframeElement}
      </Box>
    </Box>
  );
}
