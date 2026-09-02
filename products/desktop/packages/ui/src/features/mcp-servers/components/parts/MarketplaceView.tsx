import { MagnifyingGlass, Plus, X } from "@phosphor-icons/react";
import {
  MCP_CATEGORIES,
  type McpCategory,
  type McpRecommendedServer,
  type McpServerInstallation,
} from "@posthog/api-client/posthog-client";
import {
  filterServersByCategory,
  filterServersByQuery,
} from "@posthog/core/mcp-servers/filters";
import {
  Button,
  Flex,
  Heading,
  IconButton,
  Spinner,
  Text,
  TextField,
} from "@radix-ui/themes";
import { useMemo } from "react";
import { ServerCard } from "./ServerCard";

interface MarketplaceViewProps {
  servers: McpRecommendedServer[];
  serversLoading: boolean;
  installations: McpServerInstallation[];
  installingId: string | null;
  query: string;
  onQueryChange: (q: string) => void;
  category: McpCategory | "all";
  onCategoryChange: (c: McpCategory | "all") => void;
  onOpenServer: (templateId: string) => void;
  onOpenInstallation: (installationId: string) => void;
  onConnect: (server: McpRecommendedServer) => void;
  onAddCustom: () => void;
}

export function MarketplaceView({
  servers,
  serversLoading,
  installations,
  installingId,
  query,
  onQueryChange,
  category,
  onCategoryChange,
  onOpenServer,
  onOpenInstallation,
  onConnect,
  onAddCustom,
}: MarketplaceViewProps) {
  const installationByTemplateId = useMemo(() => {
    const map = new Map<string, string>();
    for (const installation of installations) {
      if (installation.template_id) {
        map.set(installation.template_id, installation.id);
      }
    }
    return map;
  }, [installations]);

  const visibleServers = useMemo(() => {
    const byCategory = filterServersByCategory(servers, category);
    return filterServersByQuery(byCategory, query);
  }, [servers, category, query]);

  const hasFilters = query !== "" || category !== "all";

  return (
    <Flex direction="column" gap="4" className="min-w-0">
      <Flex align="start" justify="between" gap="3">
        <Flex direction="column" gap="1" className="min-w-0">
          <Heading className="font-bold text-2xl">Marketplace</Heading>
          <Text color="gray" className="text-sm">
            Connect MCP servers to make them available to in PostHog on desktop
            and in the cloud.
          </Text>
        </Flex>
        <Button variant="solid" size="2" onClick={onAddCustom}>
          <Plus size={14} />
          Add custom
        </Button>
      </Flex>

      <TextField.Root
        value={query}
        onChange={(e) => onQueryChange(e.target.value)}
        placeholder="Search servers by name or capability…"
        size="2"
      >
        <TextField.Slot>
          <MagnifyingGlass size={14} />
        </TextField.Slot>
        {query && (
          <TextField.Slot>
            <IconButton
              variant="ghost"
              size="1"
              onClick={() => onQueryChange("")}
            >
              <X size={12} />
            </IconButton>
          </TextField.Slot>
        )}
      </TextField.Root>

      <Flex gap="2" wrap="wrap">
        {MCP_CATEGORIES.map((c) => (
          <button
            key={c.id}
            type="button"
            onClick={() => onCategoryChange(c.id)}
            className={`rounded-full border px-3 py-1 text-xs transition-colors ${
              category === c.id
                ? "border-accent-8 bg-accent-4 text-accent-11"
                : "border-gray-5 bg-gray-2 text-gray-11 hover:border-gray-7 hover:bg-gray-3"
            }`}
          >
            {c.label}
            {category === c.id && c.id !== "all" && (
              <span className="ml-1 text-gray-11">
                ({visibleServers.length})
              </span>
            )}
          </button>
        ))}
      </Flex>

      <Flex align="center" justify="between">
        <Text color="gray" className="text-[13px]">
          {visibleServers.length}{" "}
          {visibleServers.length === 1 ? "server" : "servers"}
        </Text>
        {hasFilters && (
          <Button
            variant="ghost"
            size="1"
            color="gray"
            onClick={() => {
              onQueryChange("");
              onCategoryChange("all");
            }}
          >
            Clear filters
          </Button>
        )}
      </Flex>

      {serversLoading ? (
        <Flex align="center" justify="center" py="6">
          <Spinner size="2" />
        </Flex>
      ) : visibleServers.length === 0 ? (
        <Flex
          align="center"
          justify="center"
          direction="column"
          gap="1"
          py="6"
          className="rounded border border-gray-6 border-dashed"
        >
          <Text className="font-medium text-sm">No servers match.</Text>
          <Text color="gray" className="text-[13px]">
            Try a different category or clear the search.
          </Text>
        </Flex>
      ) : (
        <Flex direction="column" gap="3">
          {visibleServers.map((server) => {
            const installationId = installationByTemplateId.get(server.id);
            return (
              <ServerCard
                key={server.id}
                server={server}
                installed={!!installationId}
                isInstalling={installingId === server.id}
                onOpen={() =>
                  installationId
                    ? onOpenInstallation(installationId)
                    : onOpenServer(server.id)
                }
                onConnect={() => onConnect(server)}
              />
            );
          })}
        </Flex>
      )}
    </Flex>
  );
}
