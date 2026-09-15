import { PencilSimpleIcon, SparkleIcon } from "@phosphor-icons/react";
import { Button, Text } from "@posthog/quill";

interface ContextEmptyHeroProps {
  channelName: string;
  onAskAgent: () => void;
  onWrite: () => void;
}

/** The first thing a person sees in a space with no context yet: one decision. */
export function ContextEmptyHero({
  channelName,
  onAskAgent,
  onWrite,
}: ContextEmptyHeroProps) {
  return (
    <div className="flex flex-col items-start gap-4 rounded-lg border border-border bg-card px-6 py-8">
      <div className="flex flex-col gap-1">
        <Text size="base" weight="semibold">
          Tell agents what {channelName} is about
        </Text>
        <Text size="xs" variant="muted" className="max-w-[520px]">
          An agent reads the repository and this project, then drafts the
          briefing, links the dashboards, flags, and experiments it finds, and
          proposes goals. You keep what fits.
        </Text>
      </div>
      <div className="flex items-center gap-2">
        <Button variant="primary" onClick={onAskAgent}>
          <SparkleIcon size={14} />
          Draft with agent
        </Button>
        <Button variant="outline" onClick={onWrite}>
          <PencilSimpleIcon size={14} />
          Write it myself
        </Button>
      </div>
    </div>
  );
}
