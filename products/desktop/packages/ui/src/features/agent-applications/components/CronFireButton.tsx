import {
  PlayIcon,
  SpinnerIcon,
  WarningCircleIcon,
} from "@phosphor-icons/react";
import { Button } from "@posthog/ui/primitives/Button";
import { useFireAgentCron } from "../hooks/useFireAgentCron";

/**
 * "Run now" — fires a cron trigger out-of-band (not on its schedule) so an
 * author can test it. On success, hands the created session id back so the
 * caller can jump straight to the run.
 */
export function CronFireButton({
  idOrSlug,
  revisionId,
  cronName,
  onFired,
}: {
  idOrSlug: string;
  revisionId: string;
  cronName: string;
  onFired?: (sessionId: string) => void;
}) {
  const fire = useFireAgentCron(idOrSlug, revisionId);
  return (
    <Button
      size="1"
      variant="soft"
      color={fire.isError ? "red" : "gray"}
      disabled={fire.isPending}
      onClick={() =>
        fire.mutate(
          { cronName },
          { onSuccess: (res) => onFired?.(res.session_id) },
        )
      }
    >
      {fire.isPending ? (
        <SpinnerIcon size={13} className="animate-spin" />
      ) : fire.isError ? (
        <WarningCircleIcon size={13} />
      ) : (
        <PlayIcon size={13} />
      )}
      {fire.isPending ? "Firing…" : fire.isError ? "Failed" : "Run now"}
    </Button>
  );
}
