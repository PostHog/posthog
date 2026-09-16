import { ArrowSquareOutIcon } from "@phosphor-icons/react";
import { Button, Text } from "@posthog/quill";
import type { ContextSourceState } from "@posthog/ui/features/canvas/hooks/useContextSources";
import { ServerIcon } from "@posthog/ui/features/mcp-servers/components/parts/icons";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import { useNavigate } from "@tanstack/react-router";

interface ConnectSourceCardProps {
  state: ContextSourceState;
  onConnect: () => void;
  /** Shown under the card when a link is waiting for the connection. */
  heldLink?: string | null;
}

/**
 * The step between picking a source and linking something from it. Agents can
 * only read a link through its MCP server, so an unconnected source starts
 * the authorization here instead of taking a link it cannot open.
 */
export function ConnectSourceCard({
  state,
  onConnect,
  heldLink,
}: ConnectSourceCardProps) {
  const navigate = useNavigate();
  const { source, status, connecting, needsCredentials } = state;
  const name = source.name;

  let heading: string;
  let body: string;
  let action: string;
  if (needsCredentials) {
    heading = `Connect ${name}`;
    body = `${source.purpose} ${name} needs an API key, so it connects from the MCP servers page. Come back here once it is connected.`;
    action = "Open MCP servers";
  } else if (status === "needs_reauth") {
    heading = `Reconnect ${name}`;
    body = `${name} was connected before and needs to be authorized again before agents can read what you link.`;
    action = `Reconnect ${name}`;
  } else if (status === "pending_oauth") {
    heading = `Finish connecting ${name}`;
    body = `Authorization for ${name} was started but not finished. Finishing it opens ${name} in your browser.`;
    action = "Finish authorizing";
  } else {
    heading = `Connect ${name}`;
    body = `${source.purpose} Connecting opens ${name} in your browser to authorize PostHog.`;
    action = `Connect ${name}`;
  }

  return (
    <div className="flex flex-col gap-3 rounded-md border border-border border-dashed p-4">
      <div className="flex items-start gap-3">
        <ServerIcon iconDomain={source.iconDomain} size={28} />
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          <Text size="xs" weight="medium">
            {heading}
          </Text>
          <Text size="xs" variant="muted">
            {body}
          </Text>
        </div>
      </div>
      <div className="flex items-center gap-3 pl-10">
        {needsCredentials ? (
          <Button
            variant="outline"
            size="xs"
            onClick={() => void navigate({ to: "/mcp-servers" })}
          >
            <ArrowSquareOutIcon size={12} />
            {action}
          </Button>
        ) : (
          <Button
            variant="primary"
            size="xs"
            disabled={connecting}
            onClick={onConnect}
          >
            {connecting ? <Spinner /> : null}
            {connecting ? `Waiting for ${name}` : action}
          </Button>
        )}
        <Text size="xxs" variant="muted">
          {connecting
            ? "Finish in your browser. This step closes on its own."
            : heldLink
              ? `Your link stays here until ${name} is connected.`
              : null}
        </Text>
      </div>
    </div>
  );
}
