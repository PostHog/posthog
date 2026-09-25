import {
  DEFAULT_PULL_REQUEST_LABEL,
  describePullRequestLabel,
  PULL_REQUEST_LABEL_MAX_LENGTH,
  type PullRequestLabelUpdate,
  parsePullRequestLabel,
  pullRequestLabelEnabled,
  pullRequestLabelFieldValue,
} from "@posthog/core/inbox/pullRequestLabel";
import { Button, Input, Switch, Text } from "@posthog/quill";
import type { SignalTeamConfig } from "@posthog/shared/types";
import { useState } from "react";

interface PullRequestLabelSettingsProps {
  config: SignalTeamConfig | null | undefined;
  /** Persist one or both label fields. Rejects when the server refuses the write. */
  onSave: (updates: PullRequestLabelUpdate) => Promise<void>;
  isLoading?: boolean;
  disabled?: boolean;
}

/**
 * Per-project GitHub label on the pull requests agents open. The switch turns
 * labelling on; the field names the label, and an empty field keeps the server
 * default.
 */
export function PullRequestLabelSettings({
  config,
  onSave,
  isLoading = false,
  disabled = false,
}: PullRequestLabelSettingsProps) {
  const enabled = pullRequestLabelEnabled(config);
  const savedValue = pullRequestLabelFieldValue(config);
  const [draft, setDraft] = useState(savedValue);
  const [syncedValue, setSyncedValue] = useState(savedValue);
  const [error, setError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  // Same projection the daily-limit control uses: adopt the server value when it
  // changes, and leave a typed draft alone while a save is in flight, so a
  // failed save keeps what the user typed.
  if (savedValue !== syncedValue && !isSaving) {
    setSyncedValue(savedValue);
    setDraft(savedValue);
  }

  const isDirty = draft.trim() !== savedValue;
  const controlsDisabled = disabled || isLoading || isSaving;

  const save = async (updates: PullRequestLabelUpdate) => {
    setIsSaving(true);
    try {
      await onSave(updates);
    } catch {
      // The mutation reports the failure. Nothing local changed, so the control
      // keeps showing the saved state.
    } finally {
      setIsSaving(false);
    }
  };

  const handleToggle = (checked: boolean) => {
    setError(null);
    void save({ pull_request_label_enabled: checked });
  };

  const handleSave = () => {
    const parsed = parsePullRequestLabel(draft);
    if (!parsed.ok) {
      setError(parsed.error);
      return;
    }
    setError(null);
    void save({ pull_request_label: parsed.value });
  };

  return (
    <div className="flex flex-col gap-2 border-border border-t border-dashed pt-3">
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-col gap-1">
          <Text className="font-medium text-(--gray-12) text-sm">
            Label PRs on GitHub
          </Text>
          <Text className="text-(--gray-11) text-[13px]">
            Add a label to every PR agents open, so you can find them in GitHub
            search and notification rules. PostHog creates the label if your
            repository does not have it.
          </Text>
        </div>
        <Switch
          size="sm"
          checked={enabled}
          disabled={controlsDisabled}
          aria-label="Label self-driving pull requests on GitHub"
          data-attr="pull-request-label-enabled"
          onCheckedChange={(checked) => handleToggle(checked === true)}
        />
      </div>

      {isLoading ? (
        <div className="h-[32px] w-[220px] animate-pulse rounded bg-gray-3" />
      ) : enabled ? (
        <>
          <div className="flex items-center gap-2">
            <div className="w-[220px]">
              <Input
                maxLength={PULL_REQUEST_LABEL_MAX_LENGTH}
                placeholder={DEFAULT_PULL_REQUEST_LABEL}
                aria-label="Pull request label name"
                aria-describedby={
                  error ? "pull-request-label-error" : undefined
                }
                value={draft}
                disabled={controlsDisabled}
                data-attr="pull-request-label-input"
                onChange={(e) => {
                  setDraft(e.currentTarget.value);
                  setError(null);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && isDirty) {
                    e.preventDefault();
                    handleSave();
                  }
                }}
              />
            </div>
            <Button
              size="sm"
              disabled={controlsDisabled || !isDirty}
              loading={isSaving}
              data-attr="pull-request-label-save"
              onClick={handleSave}
            >
              Save
            </Button>
          </div>

          {error ? (
            <Text
              id="pull-request-label-error"
              role="alert"
              className="text-(--red-11) text-[12.5px]"
            >
              {error}
            </Text>
          ) : (
            <Text className="text-(--gray-11) text-[12.5px]">
              {describePullRequestLabel(config)}
            </Text>
          )}
        </>
      ) : null}
    </div>
  );
}
