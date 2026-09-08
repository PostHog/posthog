import { Text } from "@posthog/quill";
import { GithubConnectionIcon } from "@posthog/ui/features/integrations/components/GithubConnectionIcon";

interface GithubConnectionLinkProps {
  connected: boolean;
  /** Shown under the link once a connection exists. */
  accountLabel?: string | null;
}

/** The link between the two marks carries the connection state. */
export function GithubConnectionLink({
  connected,
  accountLabel,
}: GithubConnectionLinkProps) {
  return (
    <div className="flex flex-col items-center gap-2">
      <div className="flex h-12 items-center justify-center">
        <div className="scale-150">
          <GithubConnectionIcon connected={connected} />
        </div>
      </div>
      {connected && accountLabel && (
        <Text size="xs" className="text-success-foreground">
          {accountLabel}
        </Text>
      )}
    </div>
  );
}
