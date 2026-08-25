import { Eye } from "@phosphor-icons/react";
import { Button, Text } from "@posthog/quill";
import { useTaskPrUrls } from "@posthog/ui/features/git-interaction/useTaskPrUrl";
import { useSessionIsCloud } from "@posthog/ui/features/sessions/useSession";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { useState } from "react";
import {
  useBabysitRunState,
  useStartBabysit,
  useStopBabysit,
} from "./useBabysitRunState";

interface BabysitDockProps {
  taskId: string;
  runId: string | undefined;
}

export function BabysitDock({ taskId, runId }: BabysitDockProps) {
  const isCloud = useSessionIsCloud(taskId);
  const { primaryUrl: prUrl } = useTaskPrUrls(taskId, isCloud);
  const { uiState, staged } = useBabysitRunState(
    isCloud ? taskId : undefined,
    prUrl ?? undefined,
  );
  const startBabysit = useStartBabysit(taskId, runId);
  const stopBabysit = useStopBabysit(taskId, runId);
  const setBabysitMode = useSettingsStore((s) => s.setBabysitMode);
  const [dismissed, setDismissed] = useState(false);

  const busy = startBabysit.isPending || stopBabysit.isPending;

  if (!isCloud || !prUrl || dismissed) return null;
  if (uiState !== "proposed" && uiState !== "attention") return null;

  const failingChecks = Array.isArray(
    (staged?.attention as { failing_checks?: unknown[] } | undefined)
      ?.failing_checks,
  )
    ? (staged?.attention as { failing_checks: unknown[] }).failing_checks.length
    : 0;

  const title =
    uiState === "attention" ? "The PR needs attention" : "Babysit this PR?";
  const body =
    uiState === "attention"
      ? failingChecks > 0
        ? `${failingChecks} failing ${failingChecks === 1 ? "check" : "checks"}. Approve babysitting and the agent will fix them.`
        : "CI or reviews need a fix. Approve babysitting and the agent will handle it."
      : "The agent will watch CI and reviews, and wake up to fix failures until the PR is green.";

  return (
    <div className="mb-2 rounded-[8px] border border-(--gray-6) bg-(--gray-2) px-4 py-3">
      <div className="flex items-start gap-3">
        <Eye size={18} className="mt-[2px] shrink-0 text-(--accent-11)" />
        <div className="min-w-0 flex-1">
          <Text className="font-medium text-(--gray-12) text-sm">{title}</Text>
          <Text className="mt-[2px] block text-(--gray-11) text-xs">
            {body}
          </Text>
        </div>
      </div>
      <div className="mt-3 flex items-center justify-end gap-2">
        <Button
          variant="link-muted"
          size="sm"
          disabled={busy}
          onClick={() => {
            setBabysitMode("always");
            startBabysit.mutate();
          }}
        >
          Always babysit
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={busy}
          onClick={() => {
            stopBabysit.mutate();
            setDismissed(true);
          }}
        >
          Not this time
        </Button>
        <Button
          variant="primary"
          size="sm"
          loading={startBabysit.isPending}
          disabled={busy}
          onClick={() => startBabysit.mutate()}
        >
          {uiState === "attention" ? "Approve babysitting" : "Babysit this PR"}
        </Button>
      </div>
    </div>
  );
}
