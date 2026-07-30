import { MagnifyingGlass, Plus, X } from "@phosphor-icons/react";
import type {
  McpRecommendedServer,
  McpServerInstallation,
} from "@posthog/api-client/posthog-client";
import type { LocalMcpCloudClassification } from "@posthog/core/local-mcp/localMcpImport";
import { filterInstallationsByQuery } from "@posthog/core/mcp-servers/filters";
import {
  resolveServerName,
  sortInstallationsByName,
} from "@posthog/core/mcp-servers/resolveServerName";
import { getInstallationStatus } from "@posthog/core/mcp-servers/status";
import { LocalMcpRailSection } from "@posthog/ui/features/local-mcp/LocalMcpRailSection";
import { PULSE_COLOR } from "@posthog/ui/features/mcp-servers/components/parts/statusBadge";
import {
  Flex,
  IconButton,
  ScrollArea,
  Text,
  TextField,
} from "@radix-ui/themes";
import { useMemo, useState } from "react";
import { ServerIcon } from "./icons";

interface McpInstalledRailProps {
  installations: McpServerInstallation[];
  templates: McpRecommendedServer[];
  localServers: LocalMcpCloudClassification[];
  selectedInstallationId: string | null;
  onAddCustom: () => void;
  onSelectInstallation: (installationId: string) => void;
}

export function McpInstalledRail({
  installations,
  templates,
  localServers,
  selectedInstallationId,
  onAddCustom,
  onSelectInstallation,
}: McpInstalledRailProps) {
  const [search, setSearch] = useState("");

  const templatesById = useMemo(() => {
    const map = new Map<string, McpRecommendedServer>();
    for (const template of templates) map.set(template.id, template);
    return map;
  }, [templates]);

  const visibleInstallations = useMemo(() => {
    const filtered = filterInstallationsByQuery(
      installations,
      templatesById,
      search,
    );
    return sortInstallationsByName(filtered, templatesById);
  }, [installations, templatesById, search]);

  return (
    <aside className="flex h-full min-h-0 w-[256px] shrink-0 flex-col border-gray-6 border-r bg-gray-2">
      <Flex
        align="center"
        justify="between"
        px="3"
        pt="3"
        pb="2"
        className="border-b border-b-(--gray-5)"
      >
        <Text className="font-bold text-sm">MCP servers</Text>
        <IconButton
          variant="ghost"
          color="gray"
          size="1"
          onClick={onAddCustom}
          title="Add custom server"
        >
          <Plus size={14} />
        </IconButton>
      </Flex>

      <Flex direction="column" gap="2" px="3" pt="3">
        <TextField.Root
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search installed…"
          size="1"
        >
          <TextField.Slot>
            <MagnifyingGlass size={12} />
          </TextField.Slot>
          {search && (
            <TextField.Slot>
              <IconButton
                variant="ghost"
                size="1"
                onClick={() => setSearch("")}
              >
                <X size={10} />
              </IconButton>
            </TextField.Slot>
          )}
        </TextField.Root>
      </Flex>

      <Flex
        align="center"
        justify="between"
        px="3"
        pt="4"
        pb="1"
        className="tracking-[0.06em]"
      >
        <Text
          color="gray"
          className="font-medium text-[10px] uppercase leading-none"
        >
          Active
        </Text>
        <Text
          color="gray"
          className="rounded-[10px] bg-(--gray-4) px-[6px] py-[1px] text-[10px] leading-none"
        >
          {visibleInstallations.length}
        </Text>
      </Flex>

      <ScrollArea className="min-h-0 flex-1">
        <Flex direction="column" gap="1" px="2" pb="3">
          {visibleInstallations.length === 0 ? (
            <Text
              color="gray"
              className="px-[10px] py-[8px] text-[13px] italic"
            >
              {search
                ? `Nothing matches "${search}".`
                : "No servers installed yet."}
            </Text>
          ) : (
            visibleInstallations.map((installation) => {
              const template = installation.template_id
                ? (templatesById.get(installation.template_id) ?? null)
                : null;
              const name = resolveServerName(installation, template);
              const status = getInstallationStatus(installation);
              const active = selectedInstallationId === installation.id;
              return (
                <button
                  key={installation.id}
                  type="button"
                  onClick={() => onSelectInstallation(installation.id)}
                  className={`grid grid-cols-[28px_1fr_auto] items-center gap-2 rounded px-2 py-1.5 text-left transition-colors ${
                    active
                      ? "bg-gray-1 text-gray-12 shadow-sm"
                      : "text-gray-11 hover:bg-gray-3"
                  }`}
                >
                  <ServerIcon
                    iconDomain={
                      installation.icon_domain || template?.icon_domain
                    }
                    serverUrl={installation.url || template?.url}
                    size={28}
                  />
                  <Flex direction="column" className="min-w-0 leading-[1.2]">
                    <Text truncate className="font-medium text-[13px]">
                      {name}
                    </Text>
                    <Text
                      color="gray"
                      truncate
                      className="text-[10px] leading-none"
                    >
                      {installation.tool_count ?? 0} tools
                    </Text>
                  </Flex>
                  <span
                    aria-hidden="true"
                    style={{
                      background: PULSE_COLOR[status],
                      boxShadow: `0 0 0 3px color-mix(in oklch, ${PULSE_COLOR[status]} 20%, transparent)`,
                    }}
                    className="h-[6px] w-[6px] rounded-full"
                  />
                </button>
              );
            })
          )}
          <LocalMcpRailSection servers={localServers} search={search} />
        </Flex>
      </ScrollArea>
    </aside>
  );
}
