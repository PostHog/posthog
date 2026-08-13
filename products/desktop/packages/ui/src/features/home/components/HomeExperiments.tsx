import { ArrowSquareOutIcon, FlaskIcon } from "@phosphor-icons/react";
import type {
  HomeExperiment,
  HomeExperimentStage,
} from "@posthog/core/home/homeSchemas";
import { Badge, Button, Card } from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { track } from "@posthog/ui/shell/analytics";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import { experimentUrl } from "@posthog/ui/utils/posthogLinks";

const STAGE_LABEL: Record<HomeExperimentStage, string> = {
  running: "Running",
  paused: "Paused",
  draft: "Draft",
  concluded: "Concluded",
};

const STAGE_TONE: Record<
  HomeExperimentStage,
  "default" | "success" | "warning"
> = {
  running: "success",
  paused: "warning",
  draft: "default",
  concluded: "default",
};

/** Whole days since a timestamp, or null when there is no timestamp. */
function daysSince(epochMs: number | null): number | null {
  if (epochMs == null) return null;
  const days = Math.floor((Date.now() - epochMs) / 86_400_000);
  return days >= 0 ? days : null;
}

/** How long the experiment has been collecting, in the plainest terms. */
function runningFor(experiment: HomeExperiment): string | null {
  if (experiment.stage === "draft") return "Not launched yet";
  const days = daysSince(experiment.startedAt);
  if (days == null) return null;
  if (days === 0) return "Started today";
  if (days === 1) return "Running for 1 day";
  return `Running for ${days} days`;
}

/**
 * An experiment as Home talks about it: where it is, how long it has been
 * there, and what it is testing. The numbers behind it stay in PostHog, so the
 * card opens there rather than restating a result it cannot compute.
 */
function ExperimentCard({ experiment }: { experiment: HomeExperiment }) {
  const url = experimentUrl(experiment.id);
  const duration = runningFor(experiment);

  const open = () => {
    if (!url) return;
    track(ANALYTICS_EVENTS.HOME_ACTION, { action_type: "open_experiment" });
    void openExternalUrl(url);
  };

  return (
    <Card className="flex flex-row items-center gap-3 p-3">
      <FlaskIcon size={16} className="shrink-0 text-muted-foreground" />
      <div className="flex min-w-0 flex-col gap-0.5">
        <div className="flex min-w-0 items-center gap-2">
          <span className="truncate font-medium text-sm">
            {experiment.name}
          </span>
          <Badge variant={STAGE_TONE[experiment.stage]}>
            {STAGE_LABEL[experiment.stage]}
          </Badge>
          {experiment.yours ? <Badge variant="info">Yours</Badge> : null}
        </div>
        <span className="truncate text-muted-foreground text-xs">
          {[
            duration,
            experiment.variants.length > 0
              ? `${experiment.variants.length} variants`
              : null,
            experiment.featureFlagKey,
          ]
            .filter(Boolean)
            .join(" · ")}
        </span>
      </div>
      <div className="ml-auto shrink-0">
        <Button variant="outline" disabled={!url} onClick={open}>
          View results
          <ArrowSquareOutIcon size={14} />
        </Button>
      </div>
    </Card>
  );
}

export function HomeExperiments({
  experiments,
}: {
  experiments: HomeExperiment[];
}) {
  return (
    <div className="flex flex-col gap-2">
      {experiments.map((experiment) => (
        <ExperimentCard key={experiment.id} experiment={experiment} />
      ))}
    </div>
  );
}
