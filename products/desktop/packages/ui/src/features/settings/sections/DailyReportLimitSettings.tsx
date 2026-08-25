import {
  dailyReportLimitFieldValue,
  describeDailyReportLimit,
  parseDailyReportLimit,
} from "@posthog/core/inbox/dailyReportLimit";
import { Button, Input, Text } from "@posthog/quill";
import type { SignalTeamConfig } from "@posthog/shared/types";
import { useState } from "react";

interface DailyReportLimitSettingsProps {
  config: SignalTeamConfig | null | undefined;
  /** Persist the cap; `null` clears it. Resolves once the server responds. */
  onSave: (limit: number | null) => Promise<void>;
  isLoading?: boolean;
  disabled?: boolean;
}

/**
 * Per-project daily cap on new reports reaching the inbox. Saving a whole number
 * sets the cap; clearing the field removes it. Today's count and the paused state
 * come from the server config.
 */
export function DailyReportLimitSettings({
  config,
  onSave,
  isLoading = false,
  disabled = false,
}: DailyReportLimitSettingsProps) {
  const savedValue = dailyReportLimitFieldValue(config);
  const [draft, setDraft] = useState(savedValue);
  const [syncedValue, setSyncedValue] = useState(savedValue);
  const [error, setError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  // Re-sync the field when the server value actually changes (a refresh, a
  // successful save, or another surface's save) so it shows through instead of
  // being masked. Deriving during render — rather than an effect keyed on
  // isSaving — leaves a failed save's typed draft in place, since a failure
  // does not change the server value.
  if (savedValue !== syncedValue && !isSaving) {
    setSyncedValue(savedValue);
    setDraft(savedValue);
  }

  const status = describeDailyReportLimit(config);
  const isDirty = draft.trim() !== savedValue;
  const controlsDisabled = disabled || isLoading || isSaving;

  const handleSave = async () => {
    const parsed = parseDailyReportLimit(draft);
    if (!parsed.ok) {
      setError(parsed.error);
      return;
    }
    setError(null);
    setIsSaving(true);
    try {
      await onSave(parsed.value);
    } finally {
      setIsSaving(false);
    }
  };

  const handleClear = async () => {
    setDraft("");
    setError(null);
    setIsSaving(true);
    try {
      await onSave(null);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="flex flex-col gap-2 border-(--gray-5) border-t border-dashed pt-3">
      <div className="flex flex-col gap-1">
        <Text className="font-medium text-(--gray-12) text-sm">
          Daily report limit
        </Text>
        <Text className="text-(--gray-11) text-[13px]">
          Cap how many new reports reach Self-driving each day. Leave the field
          empty for no limit.
        </Text>
      </div>

      {isLoading ? (
        <div className="h-[32px] w-[220px] animate-pulse rounded bg-gray-3" />
      ) : (
        <>
          <div className="flex items-center gap-2">
            <div className="w-[120px]">
              <Input
                type="number"
                min={1}
                step={1}
                inputMode="numeric"
                placeholder="No limit"
                aria-label="Daily report limit"
                aria-describedby={
                  error ? "daily-report-limit-error" : undefined
                }
                value={draft}
                disabled={controlsDisabled}
                data-attr="daily-report-limit-input"
                onChange={(e) => {
                  setDraft(e.currentTarget.value);
                  setError(null);
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && isDirty) {
                    e.preventDefault();
                    void handleSave();
                  }
                }}
              />
            </div>
            <Button
              size="sm"
              disabled={controlsDisabled || !isDirty}
              loading={isSaving}
              data-attr="daily-report-limit-save"
              onClick={() => void handleSave()}
            >
              Save
            </Button>
            {savedValue !== "" ? (
              <Button
                size="sm"
                variant="outline"
                disabled={controlsDisabled}
                data-attr="daily-report-limit-clear"
                onClick={() => void handleClear()}
              >
                Clear
              </Button>
            ) : null}
          </div>

          {error ? (
            <Text
              id="daily-report-limit-error"
              role="alert"
              className="text-(--red-11) text-[12.5px]"
            >
              {error}
            </Text>
          ) : (
            <Text className="text-(--gray-11) text-[12.5px]">
              {status.usageText}
            </Text>
          )}

          {status.reachedText ? (
            <Text className="text-(--orange-11) text-[12.5px]">
              {status.reachedText}
            </Text>
          ) : null}
        </>
      )}
    </div>
  );
}
