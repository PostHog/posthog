import {
  effectivePullRequestReadyState,
  type PullRequestReadyChoice,
  pullRequestReadyChoiceToValue,
  teamPullRequestReadyState,
  userPullRequestReadyChoice,
} from "@posthog/core/inbox/pullRequestReadyState";
import { Text } from "@posthog/quill";
import type {
  SignalTeamConfig,
  SignalUserAutonomyConfig,
} from "@posthog/shared/types";
import { SettingsSegmented } from "@posthog/ui/features/settings/components/SettingsSegmented";
import { useState } from "react";

const STATE_OPTIONS = [
  { value: "draft", label: "Draft" },
  { value: "ready", label: "Ready for review" },
];

const MY_STATE_OPTIONS = [
  { value: "default", label: "Default" },
  ...STATE_OPTIONS,
];

interface PullRequestStateSettingsProps {
  teamConfig: SignalTeamConfig | null | undefined;
  userConfig: SignalUserAutonomyConfig | null | undefined;
  /** Persist the project default. Resolves once the server responds. */
  onSaveTeamDefault: (ready: boolean) => Promise<void>;
  /** Persist this reviewer's override; `null` clears it back to the project default. */
  onSaveMine: (ready: boolean | null) => Promise<void>;
  isLoading?: boolean;
}

/**
 * The state self-driving pull requests open in. Draft is the default because a
 * ready pull request can start the full CI matrix and request reviews, which is
 * runner spend a team chooses. The personal control overrides the project one,
 * since a reviewer who reads their inbox pull requests anyway gains nothing from
 * the draft round trip.
 */
export function PullRequestStateSettings({
  teamConfig,
  userConfig,
  onSaveTeamDefault,
  onSaveMine,
  isLoading = false,
}: PullRequestStateSettingsProps) {
  const [isSavingTeam, setIsSavingTeam] = useState(false);
  const [isSavingMine, setIsSavingMine] = useState(false);

  const teamState = teamPullRequestReadyState(teamConfig);
  const myChoice = userPullRequestReadyChoice(userConfig);
  const effectiveState = effectivePullRequestReadyState(teamConfig, userConfig);

  const handleTeamChange = async (value: string) => {
    setIsSavingTeam(true);
    try {
      await onSaveTeamDefault(value === "ready");
    } finally {
      setIsSavingTeam(false);
    }
  };

  const handleMyChange = async (value: string) => {
    setIsSavingMine(true);
    try {
      await onSaveMine(
        pullRequestReadyChoiceToValue(value as PullRequestReadyChoice),
      );
    } finally {
      setIsSavingMine(false);
    }
  };

  if (isLoading) {
    return (
      <div className="flex flex-col gap-3">
        <div className="h-[32px] w-[220px] animate-pulse rounded bg-gray-3" />
        <div className="h-[32px] w-[260px] animate-pulse rounded bg-gray-3" />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        <div className="flex flex-col gap-1">
          <Text className="font-medium text-(--gray-12) text-sm">
            Project default
          </Text>
          <Text className="text-(--gray-11) text-[13px]">
            Ready for review can run more checks and request reviews. Your
            repository settings control those actions. Draft lets your team read
            the change first.
          </Text>
        </div>
        <SettingsSegmented
          ariaLabel="Project default pull request state"
          value={teamState}
          options={STATE_OPTIONS}
          disabled={isSavingTeam}
          onValueChange={(value) => void handleTeamChange(value)}
        />
      </div>

      <div className="flex flex-col gap-2 border-border border-t border-dashed pt-3">
        <div className="flex flex-col gap-1">
          <Text className="font-medium text-(--gray-12) text-sm">
            Pull requests for my review
          </Text>
          <Text className="text-(--gray-11) text-[13px]">
            This applies in every project where a report suggests you as
            reviewer, and it overrides the project default. A pull request
            someone moves back to draft stays a draft.
          </Text>
        </div>
        <SettingsSegmented
          ariaLabel="My pull request state"
          value={myChoice}
          options={MY_STATE_OPTIONS}
          disabled={isSavingMine}
          onValueChange={(value) => void handleMyChange(value)}
        />
        {myChoice === "default" ? (
          <Text className="text-(--gray-11) text-[12.5px]">
            Following this project, your pull requests open{" "}
            {effectiveState === "ready" ? "ready for review" : "as drafts"}.
          </Text>
        ) : null}
      </div>
    </div>
  );
}
