import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  Item,
  ItemContent,
  ItemDescription,
  ItemTitle,
} from "@posthog/quill";
import { REGION_LABELS } from "@posthog/shared";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import {
  useAuthStateValue,
  useCurrentUser,
} from "@posthog/ui/features/auth/authQueries";
import { useLogoutMutation } from "@posthog/ui/features/auth/useAuthMutations";
import { useOnboardingStore } from "@posthog/ui/features/onboarding/onboardingStore";
import { openSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { useSetupStore } from "@posthog/ui/features/setup/setupStore";
import { useTourStore } from "@posthog/ui/features/tour/tourStore";
import {
  RouterDevtools,
  toggleRouterDevtools,
} from "@posthog/ui/router/RouterDevtools";
import { useThemeStore } from "@posthog/ui/shell/themeStore";
import { clearApplicationStorage } from "@posthog/ui/utils/clearStorage";
import { Box, Flex, Switch, Text, Tooltip } from "@radix-ui/themes";
import { trpcClient, useTRPC } from "@renderer/trpc/client";
import { useQuery } from "@tanstack/react-query";
import { useSubscription } from "@trpc/tanstack-react-query";
import {
  Activity,
  AlertTriangle,
  Bot,
  Bug,
  ChevronDown,
  Cpu,
  FileText,
  FolderOpen,
  Globe,
  MemoryStick,
  Moon,
  Power,
  Radar,
  RefreshCw,
  RotateCcw,
  Route,
  ScrollText,
  Sun,
  Timer,
  Trash2,
  Wrench,
  X,
  ZapOff,
} from "lucide-react";
import { useMemo, useRef, useState } from "react";
import type { MetricsSample } from "../../../../main/services/dev-metrics/schemas";
import { useDevFlagsStore } from "../devFlagsStore";
import { useIpcMetricsStore } from "../ipcMetricsStore";
import { useMainThreadHealthStore } from "../mainThreadHealth";
import { AgentsPanel } from "./AgentsPanel";
import { CpuPanel } from "./CpuPanel";
import { HealthPanel } from "./HealthPanel";
import { IpcTimingsPanel } from "./IpcTimingsPanel";
import { LogsPanel } from "./LogsPanel";
import { MemoryPanel } from "./MemoryPanel";
import { NetworkPanel } from "./NetworkPanel";

type DetailPanel =
  | "cpu"
  | "memory"
  | "ipc"
  | "network"
  | "agents"
  | "logs"
  | "health"
  | null;

export function DevToolbar() {
  const devMode = useDevFlagsStore((s) => s.devMode);
  const setDevMode = useDevFlagsStore((s) => s.setDevMode);
  const reactScanEnabled = useDevFlagsStore((s) => s.reactScanEnabled);
  const setReactScanEnabledState = useDevFlagsStore(
    (s) => s.setReactScanEnabled,
  );

  const [openPanel, setOpenPanel] = useState<DetailPanel>(null);
  const [panelHeight, setPanelHeight] = useState(480);

  if (!devMode) return null;

  const togglePanel = (panel: Exclude<DetailPanel, null>) => {
    setOpenPanel((current) => (current === panel ? null : panel));
  };

  return (
    <div className="relative h-10 shrink-0 border-(--gray-6) border-t bg-(--gray-2)">
      {openPanel && (
        <PanelChrome
          openPanel={openPanel}
          onClose={() => setOpenPanel(null)}
          devMode={devMode}
          height={panelHeight}
          onResize={setPanelHeight}
        />
      )}
      <RouterDevtools />
      <Flex
        align="center"
        justify="between"
        className="h-full gap-4 px-3 font-mono text-[12px]"
      >
        <Flex align="center" gap="3" className="min-w-0">
          <EnvironmentBadge />
          <RegionBadge />
          <UserMenu />
          <Divider />
          <DevGadgets
            reactScanEnabled={reactScanEnabled}
            onToggleReactScan={() =>
              setReactScanEnabledState(!reactScanEnabled)
            }
            onToggleRouterDevtools={toggleRouterDevtools}
          />
          <Divider />
          <DebugLogsToggle />
          <Divider />
          <QuickActionsMenu />
        </Flex>

        <Flex align="center" gap="3">
          <LiveStats
            openPanel={openPanel}
            onToggleCpu={() => togglePanel("cpu")}
            onToggleMemory={() => togglePanel("memory")}
            onToggleIpc={() => togglePanel("ipc")}
            onToggleHealth={() => togglePanel("health")}
            onToggleNetwork={() => togglePanel("network")}
            onToggleAgents={() => togglePanel("agents")}
            onToggleLogs={() => togglePanel("logs")}
          />
          <Divider />
          <Tooltip content="Disable dev mode">
            <button
              type="button"
              onClick={() => {
                setOpenPanel(null);
                void setDevMode(false);
              }}
              aria-label="Disable dev mode"
              className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-(--gray-11) hover:bg-(--gray-3) hover:text-(--gray-12)"
            >
              <X size={14} />
            </button>
          </Tooltip>
        </Flex>
      </Flex>
    </div>
  );
}

function Divider() {
  return <div className="h-3 w-px bg-(--gray-6)" />;
}

const PANEL_HEADERS: Record<
  Exclude<DetailPanel, null>,
  { title: string; subtitle: string }
> = {
  cpu: {
    title: "CPU",
    subtitle: "% · total CPU usage across all Electron processes",
  },
  memory: {
    title: "Memory",
    subtitle: "GB · total working set memory (heap in tooltip)",
  },
  ipc: {
    title: "IPC traffic",
    subtitle: "ms · round-trip time of the most recent renderer→main IPC call",
  },
  network: {
    title: "Network",
    subtitle: "/min · outbound HTTP requests in the last minute",
  },
  agents: {
    title: "Agent sessions",
    subtitle: "count · active agent sessions (amber on pending permissions)",
  },
  logs: {
    title: "Logs",
    subtitle: "count · warn + error log entries since the panel last opened",
  },
  health: {
    title: "Main-thread health",
    subtitle: "ms · current main-thread event loop lag",
  },
};

function PanelChrome({
  openPanel,
  onClose,
  devMode,
  height,
  onResize,
}: {
  openPanel: Exclude<DetailPanel, null>;
  onClose: () => void;
  devMode: boolean;
  height: number;
  onResize: (next: number) => void;
}) {
  return (
    <div
      style={{ height }}
      className="absolute right-0 bottom-full left-0 z-50 flex flex-col overflow-hidden border-(--gray-6) border-t border-b bg-(--gray-2) shadow-[0_-8px_24px_-8px_rgba(0,0,0,0.3)]"
    >
      <ResizeHandle height={height} onResize={onResize} />
      <Flex
        align="center"
        justify="between"
        className="shrink-0 border-(--gray-5) border-b bg-(--gray-3) px-3 py-1.5"
      >
        <Flex align="baseline" gap="2" className="min-w-0">
          <Text size="2" weight="medium" className="text-(--gray-12)">
            {PANEL_HEADERS[openPanel].title}
          </Text>
          <Text size="1" className="truncate text-(--gray-10)">
            {PANEL_HEADERS[openPanel].subtitle}
          </Text>
        </Flex>
        <Tooltip content="Close panel">
          <button
            type="button"
            onClick={onClose}
            aria-label="Close panel"
            className="flex h-7 w-7 cursor-pointer items-center justify-center rounded-md text-(--gray-11) hover:bg-(--gray-3) hover:text-(--gray-12)"
          >
            <X size={14} />
          </button>
        </Tooltip>
      </Flex>
      <div className="min-h-0 flex-1">
        {openPanel === "cpu" && <CpuPanel enabled={devMode} />}
        {openPanel === "memory" && <MemoryPanel enabled={devMode} />}
        {openPanel === "ipc" && <IpcTimingsPanel enabled={devMode} />}
        {openPanel === "network" && <NetworkPanel enabled={devMode} />}
        {openPanel === "agents" && <AgentsPanel enabled={devMode} />}
        {openPanel === "logs" && <LogsPanel enabled={devMode} />}
        {openPanel === "health" && <HealthPanel enabled={devMode} />}
      </div>
    </div>
  );
}

const MIN_PANEL_HEIGHT = 80;
const MAX_PANEL_INSET = 60;

function ResizeHandle({
  height,
  onResize,
}: {
  height: number;
  onResize: (next: number) => void;
}) {
  const start = useRef<{ y: number; h: number } | null>(null);

  const handlePointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    e.currentTarget.setPointerCapture(e.pointerId);
    start.current = { y: e.clientY, h: height };
    document.body.style.cursor = "ns-resize";
    document.body.style.userSelect = "none";
  };

  const handlePointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!start.current) return;
    const delta = start.current.y - e.clientY;
    const max = Math.max(
      MIN_PANEL_HEIGHT,
      window.innerHeight - MAX_PANEL_INSET,
    );
    const next = Math.max(
      MIN_PANEL_HEIGHT,
      Math.min(max, start.current.h + delta),
    );
    onResize(next);
  };

  const handlePointerUp = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!start.current) return;
    e.currentTarget.releasePointerCapture(e.pointerId);
    start.current = null;
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
  };

  return (
    <div
      aria-hidden="true"
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerCancel={handlePointerUp}
      className="-top-px absolute right-0 left-0 z-10 h-1 cursor-ns-resize"
    />
  );
}

function EnvironmentBadge() {
  const isDev = import.meta.env.DEV;
  const label = isDev ? "dev" : "prod";
  const dot = isDev ? "bg-(--green-9)" : "bg-(--red-9)";
  return (
    <Flex align="center" gap="2" className="pr-1">
      <span className={`h-2 w-2 rounded-full ${dot}`} />
      <Text size="1" className="font-mono text-(--gray-12)">
        {label}
      </Text>
    </Flex>
  );
}

function RegionBadge() {
  const cloudRegion = useAuthStateValue((s) => s.cloudRegion);
  if (!cloudRegion) return null;
  const entry = REGION_LABELS[cloudRegion];
  return (
    <Flex align="center" gap="1" aria-label={entry.label}>
      <span className="text-[12px] leading-none">{entry.flag}</span>
      <Text size="1" className="font-mono text-(--gray-10)">
        {cloudRegion.toUpperCase()}
      </Text>
    </Flex>
  );
}

function UserMenu() {
  const isAuthenticated = useAuthStateValue(
    (s) => s.status === "authenticated",
  );
  const client = useOptionalAuthenticatedClient();
  const { data: user } = useCurrentUser({ client, enabled: isAuthenticated });
  const logoutMutation = useLogoutMutation();

  const handleResetOnboarding = () => {
    useOnboardingStore.getState().resetOnboarding();
    useSetupStore.getState().resetSetup();
  };

  const handleResetTours = () => {
    useTourStore.getState().resetTours();
  };

  const handleSignOut = () => {
    logoutMutation.mutate();
  };

  const emailShort = user?.email
    ? user.email.split("@")[0]
    : isAuthenticated
      ? "user"
      : "anon";

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <button
            type="button"
            className="flex h-7 cursor-pointer items-center gap-1 rounded-md px-1 font-mono text-(--gray-12) hover:bg-(--gray-3)"
            aria-label="User menu"
          >
            <span>{emailShort}</span>
            <ChevronDown size={12} className="text-(--gray-9)" />
          </button>
        }
      />
      <DropdownMenuContent align="start" className="min-w-[240px] pt-0">
        {isAuthenticated && user && (
          <Box className="-mx-1 mb-1 border-border border-b">
            <Item className="p-2">
              <ItemContent>
                {(user.first_name || user.last_name) && (
                  <ItemTitle>
                    {[user.first_name, user.last_name]
                      .filter(Boolean)
                      .join(" ")}
                  </ItemTitle>
                )}
                <ItemDescription className="text-[11px]">
                  {user.email}
                </ItemDescription>
              </ItemContent>
            </Item>
          </Box>
        )}
        <DropdownMenuGroup>
          <DropdownMenuItem onClick={() => openSettings("advanced")}>
            <Bug size={12} className="mr-2 text-(--gray-9)" />
            Open advanced settings
          </DropdownMenuItem>
          <DropdownMenuItem onClick={handleResetOnboarding}>
            <RotateCcw size={12} className="mr-2 text-(--gray-9)" />
            Reset onboarding
          </DropdownMenuItem>
          <DropdownMenuItem onClick={handleResetTours}>
            <RotateCcw size={12} className="mr-2 text-(--gray-9)" />
            Reset product tours
          </DropdownMenuItem>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuGroup>
          <DropdownMenuItem
            variant="destructive"
            onClick={clearApplicationStorage}
          >
            <Trash2 size={12} className="mr-2" />
            Clear application storage
          </DropdownMenuItem>
          {isAuthenticated && (
            <DropdownMenuItem
              variant="destructive"
              onClick={handleSignOut}
              disabled={logoutMutation.isPending}
            >
              <X size={12} className="mr-2" />
              Sign out
            </DropdownMenuItem>
          )}
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

interface DevGadgetsProps {
  reactScanEnabled: boolean;
  onToggleReactScan: () => void;
  onToggleRouterDevtools: () => void;
}

function DevGadgets({
  reactScanEnabled,
  onToggleReactScan,
  onToggleRouterDevtools,
}: DevGadgetsProps) {
  const isDarkMode = useThemeStore((s) => s.isDarkMode);
  const setTheme = useThemeStore((s) => s.setTheme);

  return (
    <Flex align="center" gap="1">
      <GadgetButton
        label={isDarkMode ? "Switch to light mode" : "Switch to dark mode"}
        onClick={() => setTheme(isDarkMode ? "light" : "dark")}
        active={false}
      >
        {isDarkMode ? <Sun size={14} /> : <Moon size={14} />}
      </GadgetButton>
      <GadgetButton
        label={reactScanEnabled ? "Disable react-scan" : "Enable react-scan"}
        onClick={onToggleReactScan}
        active={reactScanEnabled}
      >
        <Radar size={14} />
      </GadgetButton>
      {/* Router devtools are DEV-only — the overlay's code is stripped from
          prod builds, so the trigger must be too. */}
      {import.meta.env.DEV && (
        <GadgetButton
          label="Toggle router devtools"
          onClick={onToggleRouterDevtools}
          active={false}
        >
          <Route size={14} />
        </GadgetButton>
      )}
    </Flex>
  );
}

function GadgetButton({
  label,
  onClick,
  active,
  children,
}: {
  label: string;
  onClick: () => void;
  active: boolean;
  children: React.ReactNode;
}) {
  return (
    <Tooltip content={label}>
      <button
        type="button"
        onClick={onClick}
        aria-label={label}
        aria-pressed={active}
        className={`flex h-7 w-7 cursor-pointer items-center justify-center rounded-md ${
          active
            ? "bg-(--accent-3) text-(--accent-11)"
            : "text-(--gray-11) hover:bg-(--gray-3) hover:text-(--gray-12)"
        }`}
      >
        {children}
      </button>
    </Tooltip>
  );
}

/**
 * Mirrors the "Debug logs for cloud runs" toggle from Settings → Advanced so it
 * can be flipped without leaving the current view. Reads/writes the same
 * `debugLogsCloudRuns` setting, so the two controls stay in sync.
 */
function DebugLogsToggle() {
  const debugLogsCloudRuns = useSettingsStore((s) => s.debugLogsCloudRuns);
  const setDebugLogsCloudRuns = useSettingsStore(
    (s) => s.setDebugLogsCloudRuns,
  );

  return (
    <Tooltip content="Show debug-level console output in the conversation view for cloud-executed runs">
      <Flex align="center" gap="2" className="text-(--gray-11)">
        <Text size="1">Debug logs</Text>
        <Switch
          checked={debugLogsCloudRuns}
          onCheckedChange={setDebugLogsCloudRuns}
          size="1"
        />
      </Flex>
    </Tooltip>
  );
}

interface LiveStatsProps {
  openPanel: DetailPanel;
  onToggleCpu: () => void;
  onToggleMemory: () => void;
  onToggleIpc: () => void;
  onToggleHealth: () => void;
  onToggleNetwork: () => void;
  onToggleAgents: () => void;
  onToggleLogs: () => void;
}

const NETWORK_PILL_WINDOW_MS = 60_000;

function LiveStats({
  openPanel,
  onToggleCpu,
  onToggleMemory,
  onToggleIpc,
  onToggleHealth,
  onToggleNetwork,
  onToggleAgents,
  onToggleLogs,
}: LiveStatsProps) {
  const trpcReact = useTRPC();
  const devMode = useDevFlagsStore((s) => s.devMode);
  const reactScanEnabled = useDevFlagsStore((s) => s.reactScanEnabled);
  const updatesEnabled = devMode && !reactScanEnabled;
  const [sample, setSample] = useState<MetricsSample | null>(null);
  const [netTimestamps, setNetTimestamps] = useState<number[]>([]);
  const [logWarnings, setLogWarnings] = useState(0);
  const fps = useMainThreadHealthStore((s) => s.fps);
  const longTaskCount = useMainThreadHealthStore((s) => s.longTaskCount);
  const ipcEntries = useIpcMetricsStore((s) => s.entries);
  const ipcInFlight = useIpcMetricsStore((s) => s.inFlight);

  const { data: agentsData } = useQuery({
    ...trpcReact.dev.getAgentsSnapshot.queryOptions(),
    enabled: devMode,
    refetchInterval: devMode ? 2000 : false,
  });
  const activeAgents = agentsData?.sessions.length ?? 0;
  const pendingPerms = agentsData?.pendingPermissions.length ?? 0;

  useSubscription(
    trpcReact.dev.onMetrics.subscriptionOptions(undefined, {
      enabled: updatesEnabled,
      onData: setSample,
    }),
  );

  useSubscription(
    trpcReact.dev.onNetworkRequest.subscriptionOptions(undefined, {
      enabled: devMode,
      onData: () => {
        const now = Date.now();
        setNetTimestamps((prev) => {
          const next = [...prev, now];
          const cutoff = now - NETWORK_PILL_WINDOW_MS;
          return next.filter((t) => t >= cutoff);
        });
      },
    }),
  );

  useSubscription(
    trpcReact.dev.onLogEntry.subscriptionOptions(undefined, {
      enabled: devMode,
      onData: (entry) => {
        if (entry.level === "error" || entry.level === "warn") {
          setLogWarnings((n) => n + 1);
        }
      },
    }),
  );

  const ipcRecentAvg = useMemo(() => {
    if (ipcEntries.length === 0) return null;
    const cutoff = Date.now() - 5000;
    const recent = ipcEntries.filter((e) => e.startedAt >= cutoff);
    if (recent.length === 0) return null;
    const total = recent.reduce((sum, e) => sum + e.rttMs, 0);
    return total / recent.length;
  }, [ipcEntries]);

  const memoryGb = sample ? sample.totalMemoryMb / 1024 : null;
  const ipcLastColor =
    ipcRecentAvg == null
      ? undefined
      : ipcRecentAvg > 100
        ? ("red" as const)
        : ipcRecentAvg > 30
          ? ("amber" as const)
          : undefined;

  const memoryDisplay =
    memoryGb != null
      ? memoryGb >= 1
        ? `${memoryGb.toFixed(2)}GB`
        : `${(memoryGb * 1024).toFixed(0)}MB`
      : "—";
  const heapDisplay = sample ? `${sample.heapUsedMb.toFixed(0)}MB heap` : null;

  const loopLagMs = sample?.loopLagMs ?? null;
  const loopColor =
    loopLagMs == null
      ? undefined
      : loopLagMs > 50
        ? ("red" as const)
        : loopLagMs > 20
          ? ("amber" as const)
          : fps < 30
            ? ("red" as const)
            : fps < 50
              ? ("amber" as const)
              : undefined;

  const netCount = netTimestamps.length;
  const agentsValue =
    activeAgents === 0 && pendingPerms === 0
      ? "0"
      : pendingPerms > 0
        ? `${activeAgents} · ${pendingPerms}!`
        : `${activeAgents}`;
  const agentsEmphasis = pendingPerms > 0 ? ("amber" as const) : undefined;
  const logsEmphasis = logWarnings > 0 ? ("amber" as const) : undefined;

  return (
    <Flex align="center" gap="1" className="text-(--gray-11) text-[12px]">
      <StatPill
        label="CPU"
        value={sample ? `${sample.totalCpuPercent.toFixed(1)}%` : "—"}
        icon={<Cpu size={12} />}
        active={openPanel === "cpu"}
        onClick={onToggleCpu}
        emphasis={
          sample && sample.totalCpuPercent > 50
            ? "red"
            : sample && sample.totalCpuPercent > 20
              ? "amber"
              : undefined
        }
      />
      <StatPill
        label="Mem"
        value={memoryDisplay}
        tooltip={heapDisplay ?? undefined}
        icon={<MemoryStick size={12} />}
        active={openPanel === "memory"}
        onClick={onToggleMemory}
      />
      <StatPill
        label="IPC"
        value={ipcRecentAvg != null ? formatRttCompact(ipcRecentAvg) : "—"}
        tooltip={
          ipcInFlight > 0
            ? `${ipcInFlight} in flight · 5s avg RTT`
            : "5s avg RTT"
        }
        icon={<Activity size={12} />}
        active={openPanel === "ipc"}
        onClick={onToggleIpc}
        emphasis={ipcLastColor}
      />
      <StatPill
        label="Loop"
        value={loopLagMs != null ? `${loopLagMs.toFixed(0)}ms` : "—"}
        tooltip={`renderer ${fps}fps · ${longTaskCount} long tasks`}
        icon={<Timer size={12} />}
        active={openPanel === "health"}
        onClick={onToggleHealth}
        emphasis={loopColor}
      />
      <StatPill
        label="Net"
        value={`${netCount}/min`}
        icon={<Globe size={12} />}
        active={openPanel === "network"}
        onClick={onToggleNetwork}
      />
      <StatPill
        label="Agents"
        value={agentsValue}
        tooltip={
          pendingPerms > 0
            ? `${pendingPerms} pending permission${pendingPerms === 1 ? "" : "s"}`
            : undefined
        }
        icon={<Bot size={12} />}
        active={openPanel === "agents"}
        onClick={onToggleAgents}
        emphasis={agentsEmphasis}
      />
      <StatPill
        label="Logs"
        value={logWarnings > 0 ? formatCompact(logWarnings) : "0"}
        tooltip="warn + error since panel opened"
        icon={<ScrollText size={12} />}
        active={openPanel === "logs"}
        onClick={onToggleLogs}
        emphasis={logsEmphasis}
      />
    </Flex>
  );
}

function StatPill({
  label,
  value,
  icon,
  active,
  onClick,
  emphasis,
  tooltip,
}: {
  label: string;
  value: string;
  icon: React.ReactNode;
  active: boolean;
  onClick: () => void;
  emphasis?: "red" | "amber";
  tooltip?: string;
}) {
  const valueColor =
    emphasis === "red"
      ? "text-(--red-11)"
      : emphasis === "amber"
        ? "text-(--amber-11)"
        : "text-(--gray-12)";
  const pill = (
    <button
      type="button"
      onClick={onClick}
      className={`flex h-7 cursor-pointer items-center gap-1.5 rounded-md px-2.5 font-mono ${
        active
          ? "bg-(--accent-3) text-(--accent-11)"
          : "hover:bg-(--gray-3) hover:text-(--gray-12)"
      }`}
      aria-pressed={active}
    >
      <span className="text-(--gray-10)">{icon}</span>
      <span className="text-(--gray-10)">{label}</span>
      <span className={`font-medium ${valueColor}`}>{value}</span>
    </button>
  );
  return tooltip ? <Tooltip content={tooltip}>{pill}</Tooltip> : pill;
}

function formatCompact(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (value >= 1_000) return `${(value / 1_000).toFixed(1)}k`;
  return String(value);
}

function formatRttCompact(ms: number): string {
  if (ms < 1) return `${(ms * 1000).toFixed(0)}μs`;
  if (ms < 10) return `${ms.toFixed(1)}ms`;
  return `${ms.toFixed(0)}ms`;
}

const SLOW_PRESETS_MS = [0, 250, 1000, 3000] as const;

function QuickActionsMenu() {
  const trpcReact = useTRPC();
  const { data: sim, refetch: refetchSim } = useQuery({
    ...trpcReact.dev.getNetworkSim.queryOptions(),
  });
  useSubscription(
    trpcReact.dev.onNetworkSimChanged.subscriptionOptions(undefined, {
      onData: () => void refetchSim(),
    }),
  );

  const offline = sim?.offline ?? false;
  const slowMs = sim?.slowDelayMs ?? 0;

  const setOffline = (next: boolean) =>
    void trpcClient.dev.setNetworkSim.mutate({ offline: next });
  const setSlow = (ms: number) =>
    void trpcClient.dev.setNetworkSim.mutate({ slowDelayMs: ms });

  const triggerInfoToast = () =>
    void trpcClient.dev.triggerToast.mutate({
      variant: "info",
      message: "Dev toast (info) from quick actions",
    });
  const triggerErrorToast = () =>
    void trpcClient.dev.triggerToast.mutate({
      variant: "error",
      message: "Dev toast (error) from quick actions",
    });

  const handleCrash = () => {
    const ok = window.confirm(
      "Crash the main process? This will exit the app without saving in-flight work.",
    );
    if (ok) void trpcClient.dev.crashMain.mutate();
  };

  const handleRestart = () => {
    const ok = window.confirm("Restart the main process now?");
    if (ok) void trpcClient.dev.restartMain.mutate();
  };

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        render={
          <button
            type="button"
            className="flex h-7 cursor-pointer items-center gap-1 rounded-md px-1.5 text-(--gray-11) hover:bg-(--gray-3) hover:text-(--gray-12)"
            aria-label="Quick actions"
          >
            <Wrench size={14} />
            <ChevronDown size={12} className="text-(--gray-9)" />
          </button>
        }
      />
      <DropdownMenuContent align="start" className="min-w-[240px]">
        <DropdownMenuGroup>
          <DropdownMenuLabel>Open</DropdownMenuLabel>
          <DropdownMenuItem
            onClick={() => void trpcClient.dev.openUserDataDir.mutate()}
          >
            <FolderOpen size={12} className="mr-2 text-(--gray-9)" />
            Open user data dir
          </DropdownMenuItem>
          <DropdownMenuItem
            onClick={() => void trpcClient.dev.openLogFile.mutate()}
          >
            <FileText size={12} className="mr-2 text-(--gray-9)" />
            Open log file
          </DropdownMenuItem>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuGroup>
          <DropdownMenuLabel>Process</DropdownMenuLabel>
          <DropdownMenuItem
            onClick={() => void trpcClient.dev.reloadRenderer.mutate()}
          >
            <RefreshCw size={12} className="mr-2 text-(--gray-9)" />
            Reload renderer
          </DropdownMenuItem>
          <DropdownMenuItem onClick={handleRestart}>
            <Power size={12} className="mr-2 text-(--gray-9)" />
            Restart main process
          </DropdownMenuItem>
          <DropdownMenuItem variant="destructive" onClick={handleCrash}>
            <AlertTriangle size={12} className="mr-2" />
            Crash main (test crash reporting)
          </DropdownMenuItem>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuGroup>
          <DropdownMenuLabel>Simulate</DropdownMenuLabel>
          <DropdownMenuItem onClick={() => setOffline(!offline)}>
            <ZapOff
              size={12}
              className={`mr-2 ${offline ? "text-(--amber-11)" : "text-(--gray-9)"}`}
            />
            {offline ? "Disable offline mode" : "Simulate offline"}
          </DropdownMenuItem>
          {SLOW_PRESETS_MS.map((ms) => (
            <DropdownMenuItem key={`slow-${ms}`} onClick={() => setSlow(ms)}>
              <Timer
                size={12}
                className={`mr-2 ${
                  ms === slowMs ? "text-(--accent-11)" : "text-(--gray-9)"
                }`}
              />
              {ms === 0 ? "Disable network delay" : `Add ${ms}ms network delay`}
              {ms === slowMs && (
                <span className="ml-auto text-(--accent-11) text-[10px]">
                  active
                </span>
              )}
            </DropdownMenuItem>
          ))}
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        <DropdownMenuGroup>
          <DropdownMenuLabel>Toasts</DropdownMenuLabel>
          <DropdownMenuItem onClick={triggerInfoToast}>
            <Activity size={12} className="mr-2 text-(--gray-9)" />
            Trigger info toast
          </DropdownMenuItem>
          <DropdownMenuItem variant="destructive" onClick={triggerErrorToast}>
            <AlertTriangle size={12} className="mr-2" />
            Trigger error toast
          </DropdownMenuItem>
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
