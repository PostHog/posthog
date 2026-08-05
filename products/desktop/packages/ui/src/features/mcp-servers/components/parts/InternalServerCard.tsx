import { CheckCircle } from "@phosphor-icons/react";
import type { FlaggedMcpServerPayload } from "@posthog/core/local-mcp/schemas";
import { Badge, Button, Spinner, Text } from "@posthog/quill";
import { ServerIcon } from "./icons";

export interface InternalServerCardData {
  server: FlaggedMcpServerPayload;
  installed: boolean;
  isInstalling: boolean;
  hasError: boolean;
  onConnect: () => void;
}

/**
 * Marketplace card for a flag-delivered internal server. Connecting writes a
 * user-scoped entry to the local agent config instead of creating a cloud
 * installation, so unlike ServerCard there is no detail view and the card is
 * not clickable.
 */
export function InternalServerCard({
  server,
  installed,
  isInstalling,
  hasError,
  onConnect,
}: InternalServerCardData) {
  return (
    <div className="relative rounded-md border border-gray-5 bg-gray-2">
      <div className="flex w-full flex-col gap-3 p-4">
        <div className="flex w-full items-center gap-3">
          <ServerIcon iconDomain={server.iconDomain} size={36} />
          <div className="flex min-w-0 flex-1 flex-col gap-1">
            <div className="flex items-center gap-2">
              <Text className="truncate font-medium text-base">
                {server.displayName ?? server.name}
              </Text>
              {installed && (
                <CheckCircle
                  size={14}
                  weight="fill"
                  className="shrink-0 text-green-10"
                />
              )}
            </div>
            {server.description && (
              <Text variant="muted" className="line-clamp-2 text-[13px]">
                {server.description}
              </Text>
            )}
          </div>
          {/* Spacer to reserve room for the action button overlay */}
          <div style={{ width: installed ? 100 : 84 }} />
        </div>
        <div className="flex w-full items-center gap-2">
          <Badge variant="info">Internal</Badge>
          {hasError && (
            <Text variant="muted" className="text-[13px]">
              Couldn't add the server. Try again.
            </Text>
          )}
        </div>
      </div>
      <div className="absolute top-4 right-4">
        {installed ? (
          <Button variant="outline" disabled>
            Connected
          </Button>
        ) : (
          <Button variant="primary" onClick={onConnect} disabled={isInstalling}>
            {isInstalling ? <Spinner /> : null}
            Connect
          </Button>
        )}
      </div>
    </div>
  );
}
