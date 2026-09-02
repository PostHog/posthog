import { Check, MagnifyingGlass, X } from "@phosphor-icons/react";
import type {
  McpGatewayServer,
  McpRecommendedServer,
} from "@posthog/api-client/posthog-client";
import type { GatewayRoute } from "@posthog/ui/features/mcp-gateway/gatewayRoute";
import { useGatewayConfig } from "@posthog/ui/features/mcp-gateway/hooks/useGatewayConfig";
import { useGatewayServers } from "@posthog/ui/features/mcp-gateway/hooks/useGatewayServers";
import { ServerIcon } from "@posthog/ui/features/mcp-servers/components/parts/icons";
import { toast } from "@posthog/ui/primitives/toast";
import {
  Button,
  Flex,
  Heading,
  IconButton,
  Separator,
  Switch,
  Text,
  TextField,
} from "@radix-ui/themes";
import { useMemo, useState } from "react";

const SERVER_PREVIEW_LIMIT = 10;

/**
 * One row in the server-access list. The registry is sparse: untouched
 * catalog templates have no gateway row and follow the team default until an
 * admin toggles them (which materializes a row).
 */
type ServerAccessEntry =
  | { kind: "server"; server: McpGatewayServer }
  | { kind: "template"; template: McpRecommendedServer };

interface GatewayTeamSettingsProps {
  onNavigate: (route: GatewayRoute) => void;
}

/** Admin settings: custom-server gate and server access. */
export function GatewayTeamSettings({ onNavigate }: GatewayTeamSettingsProps) {
  const {
    allowCustomServers,
    allowMemberAgentAccess,
    defaultServersEnabled,
    updateSettings,
  } = useGatewayConfig();
  const {
    servers,
    recommendedTemplates,
    templatesById,
    updateServer,
    setTemplateEnabled,
    setAllEnabled,
    setAllEnabledPending,
  } = useGatewayServers();
  const [serverSearch, setServerSearch] = useState("");
  const [serversExpanded, setServersExpanded] = useState(false);

  const totalCount = servers.length + recommendedTemplates.length;
  const enabledCount =
    servers.filter((server) => server.is_team_enabled).length +
    (defaultServersEnabled ? recommendedTemplates.length : 0);
  const filteredEntries = useMemo(() => {
    const search = serverSearch.trim().toLowerCase();
    const entries: ServerAccessEntry[] = [
      ...servers.map((server) => ({ kind: "server" as const, server })),
      ...recommendedTemplates.map((template) => ({
        kind: "template" as const,
        template,
      })),
    ];
    const entryName = (entry: ServerAccessEntry) =>
      entry.kind === "server" ? entry.server.name : entry.template.name;
    return entries
      .filter(
        (entry) => !search || entryName(entry).toLowerCase().includes(search),
      )
      .sort((first, second) =>
        entryName(first).localeCompare(entryName(second), undefined, {
          sensitivity: "base",
        }),
      );
  }, [serverSearch, servers, recommendedTemplates]);
  const displayedEntries = serversExpanded
    ? filteredEntries
    : filteredEntries.slice(0, SERVER_PREVIEW_LIMIT);

  return (
    <Flex direction="column" gap="4" className="min-w-0">
      <Heading className="font-bold text-2xl">Team settings</Heading>

      <Text className="font-medium text-base">Custom servers</Text>
      <Flex
        align="center"
        justify="between"
        gap="3"
        className="rounded-md border border-gray-5 bg-gray-2 p-3"
      >
        <div>
          <Text as="div" className="font-medium text-sm">
            Allow custom servers
          </Text>
          <Text as="div" color="gray" className="text-[13px]">
            Members can add their own MCP servers, the same way admins do.
          </Text>
        </div>
        <Switch
          checked={allowCustomServers}
          onCheckedChange={(allowed) =>
            updateSettings(
              { allow_custom_servers: allowed },
              {
                onSuccess: () => {
                  if (allowed)
                    toast.success("Members can now add custom servers");
                  else toast.info("Custom servers are admin-only again");
                },
              },
            )
          }
        />
      </Flex>

      <Text className="font-medium text-base">Agent access</Text>
      <Flex
        align="center"
        justify="between"
        gap="3"
        className="rounded-md border border-gray-5 bg-gray-2 p-3"
      >
        <div>
          <Text as="div" className="font-medium text-sm">
            Allow members to manage agent access
          </Text>
          <Text as="div" color="gray" className="text-[13px]">
            Members can share connections with agents and choose which tools
            those agents may call. Turn this off to make those controls
            admin-only.
          </Text>
        </div>
        <Switch
          checked={allowMemberAgentAccess}
          onCheckedChange={(allowed) =>
            updateSettings(
              { allow_member_agent_access: allowed },
              {
                onSuccess: () => {
                  if (allowed)
                    toast.success("Members can now manage agent access");
                  else toast.info("Agent access is admin-only again");
                },
              },
            )
          }
        />
      </Flex>

      <Separator size="4" />

      <Text className="font-medium text-base">Server access</Text>
      <Text color="gray" className="text-[13px]">
        Everything is shared with the team by default. Disable everything to
        curate up from zero — servers added to the catalog later stay off too —
        or switch off individual servers.
      </Text>
      <Flex align="center" justify="between" gap="2" wrap="wrap">
        <Text color="gray" className="text-[13px]">
          {enabledCount} of {totalCount} servers enabled
        </Text>
        <Flex align="center" gap="2">
          <TextField.Root
            value={serverSearch}
            onChange={(event) => {
              setServerSearch(event.target.value);
              setServersExpanded(false);
            }}
            placeholder="Search servers…"
            size="1"
          >
            <TextField.Slot>
              <MagnifyingGlass size={12} />
            </TextField.Slot>
            {serverSearch && (
              <TextField.Slot>
                <IconButton
                  variant="ghost"
                  size="1"
                  onClick={() => {
                    setServerSearch("");
                    setServersExpanded(false);
                  }}
                >
                  <X size={10} />
                </IconButton>
              </TextField.Slot>
            )}
          </TextField.Root>
          <Button
            variant="ghost"
            color="gray"
            size="1"
            disabled={
              setAllEnabledPending ||
              (defaultServersEnabled && enabledCount === totalCount)
            }
            onClick={() => setAllEnabled(true)}
          >
            <Check size={12} /> Enable all
          </Button>
          <Button
            variant="ghost"
            color="gray"
            size="1"
            disabled={
              setAllEnabledPending ||
              (!defaultServersEnabled && enabledCount === 0)
            }
            onClick={() => setAllEnabled(false)}
          >
            <X size={12} /> Disable all
          </Button>
        </Flex>
      </Flex>
      <div className="overflow-hidden rounded border border-gray-5 bg-gray-2">
        {displayedEntries.map((entry) =>
          entry.kind === "server" ? (
            <Flex
              key={entry.server.id}
              align="center"
              gap="3"
              className={`border-gray-5 border-b px-3 py-2 last:border-b-0 ${entry.server.is_team_enabled ? "" : "opacity-60"}`}
            >
              <button
                type="button"
                className="flex min-w-0 flex-1 items-center gap-3 rounded-sm text-left outline-none hover:text-gray-12 focus-visible:ring-(--focus-8) focus-visible:ring-2"
                onClick={() =>
                  onNavigate({ view: "server", serverId: entry.server.id })
                }
              >
                <ServerIcon
                  iconDomain={
                    entry.server.template_id
                      ? templatesById.get(entry.server.template_id)?.icon_domain
                      : undefined
                  }
                  serverUrl={entry.server.url}
                  size={26}
                />
                <Flex direction="column" className="min-w-0 flex-1">
                  <Text truncate className="font-medium text-sm">
                    {entry.server.name}
                  </Text>
                  <Text color="gray" className="text-xs">
                    {entry.server.tool_count}{" "}
                    {entry.server.tool_count === 1 ? "tool" : "tools"}
                  </Text>
                </Flex>
              </button>
              <Switch
                size="1"
                checked={entry.server.is_team_enabled}
                onCheckedChange={(enabled) =>
                  updateServer(
                    {
                      serverId: entry.server.id,
                      updates: { is_team_enabled: enabled },
                    },
                    {
                      onSuccess: () => {
                        if (enabled)
                          toast.success(
                            `${entry.server.name} enabled for the team`,
                          );
                        else toast.info(`${entry.server.name} disabled`);
                      },
                    },
                  )
                }
              />
            </Flex>
          ) : (
            // Untouched catalog template: no gateway row, so no detail page.
            // Toggling it materializes a row via set_template_enabled.
            <Flex
              key={entry.template.id}
              align="center"
              gap="3"
              className={`border-gray-5 border-b px-3 py-2 last:border-b-0 ${defaultServersEnabled ? "" : "opacity-60"}`}
            >
              <Flex align="center" gap="3" className="min-w-0 flex-1">
                <ServerIcon
                  iconDomain={entry.template.icon_domain}
                  serverUrl={entry.template.url}
                  size={26}
                />
                <Flex direction="column" className="min-w-0 flex-1">
                  <Text truncate className="font-medium text-sm">
                    {entry.template.name}
                  </Text>
                  <Text color="gray" className="text-xs">
                    Catalog server — follows the team default
                  </Text>
                </Flex>
              </Flex>
              <Switch
                size="1"
                checked={defaultServersEnabled}
                onCheckedChange={(enabled) =>
                  setTemplateEnabled(
                    { templateId: entry.template.id, enabled },
                    {
                      onSuccess: () => {
                        if (enabled)
                          toast.success(
                            `${entry.template.name} enabled for the team`,
                          );
                        else toast.info(`${entry.template.name} disabled`);
                      },
                    },
                  )
                }
              />
            </Flex>
          ),
        )}
        {filteredEntries.length === 0 && (
          <Text color="gray" className="block px-3 py-3 text-[13px] italic">
            No servers match &ldquo;{serverSearch}&rdquo;.
          </Text>
        )}
        {filteredEntries.length > SERVER_PREVIEW_LIMIT && (
          <button
            type="button"
            className="w-full px-3 py-2 text-center font-medium text-gray-11 text-xs transition-colors hover:bg-gray-3 hover:text-gray-12"
            onClick={() => setServersExpanded((expanded) => !expanded)}
          >
            {serversExpanded ? "View less" : "View more"}
          </button>
        )}
      </div>
    </Flex>
  );
}
