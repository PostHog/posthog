import { CaretRight, CheckCircle } from "@phosphor-icons/react";
import {
  MCP_CATEGORIES,
  type McpRecommendedServer,
} from "@posthog/api-client/posthog-client";
import { Badge, Button, Flex, Spinner, Text } from "@radix-ui/themes";
import { ServerIcon } from "./icons";

interface ServerCardProps {
  server: McpRecommendedServer;
  installed: boolean;
  isInstalling: boolean;
  onOpen: () => void;
  onConnect: () => void;
}

export function ServerCard({
  server,
  installed,
  isInstalling,
  onOpen,
  onConnect,
}: ServerCardProps) {
  const categoryLabel = MCP_CATEGORIES.find(
    (c) => c.id === server.category,
  )?.label;

  return (
    <div className="group relative rounded-md border border-gray-5 bg-gray-2 transition-colors hover:border-gray-7 hover:bg-gray-3">
      <button
        type="button"
        onClick={onOpen}
        className="flex w-full flex-col gap-3 rounded-md p-4 text-left"
      >
        <Flex align="center" gap="3" width="100%">
          <ServerIcon
            iconDomain={server.icon_domain}
            serverUrl={server.url}
            size={36}
          />
          <Flex direction="column" gap="1" className="min-w-0 flex-1">
            <Flex align="center" gap="2">
              <Text truncate className="font-medium text-base">
                {server.name}
              </Text>
              {installed && (
                <CheckCircle
                  size={14}
                  weight="fill"
                  className="shrink-0 text-green-10"
                />
              )}
            </Flex>
            {server.description && (
              <Text
                color="gray"
                style={{
                  display: "-webkit-box",
                  WebkitLineClamp: 2,
                  WebkitBoxOrient: "vertical",
                }}
                className="overflow-hidden text-[13px]"
              >
                {server.description}
              </Text>
            )}
          </Flex>
          {/* Spacer to reserve room for the action button overlay */}
          <div style={{ width: installed ? 100 : 84 }} />
        </Flex>
        <Flex align="center" gap="2" justify="between" width="100%">
          <Flex gap="2" align="center">
            {categoryLabel && (
              <Badge color="gray" variant="soft" size="1">
                {categoryLabel}
              </Badge>
            )}
            <Badge color="gray" variant="outline" size="1">
              {server.auth_type === "oauth" ? "OAuth" : "API key"}
            </Badge>
          </Flex>
        </Flex>
      </button>
      <div className="absolute top-4 right-4">
        {installed ? (
          <Button variant="soft" color="gray" size="1" onClick={onOpen}>
            Configure
            <CaretRight size={12} />
          </Button>
        ) : (
          <Button
            variant="solid"
            size="1"
            onClick={onConnect}
            disabled={isInstalling}
          >
            {isInstalling ? <Spinner size="1" /> : null}
            Connect
          </Button>
        )}
      </div>
    </div>
  );
}
