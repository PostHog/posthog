import { Text } from "@components/text";
import { CaretDown, GithubLogo } from "phosphor-react-native";
import { type MutableRefObject, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Pressable,
  Switch,
  TextInput,
  View,
} from "react-native";
import { MarkdownText } from "@/features/chat/components/MarkdownText";
import { useThemeColors } from "@/lib/theme";
import { RepositoryPickerInline } from "../composer/RepositoryPickerInline";
import { useIntegrations } from "../hooks/useIntegrations";
import type {
  CreateTaskAutomationOptions,
  RepositorySelection,
} from "../types";
import {
  type AutomationScheduleDraft,
  buildCronExpression,
  createDefaultScheduleDraft,
  deriveAutomationName,
  parseCronExpression,
} from "../utils/automationSchedule";
import {
  findRepositoryOption,
  isRepositorySelectionComplete,
  toRepositorySelection,
} from "../utils/repositorySelection";
import { GitHubConnectionPrompt } from "./GitHubConnectionPrompt";
import { GitHubLoadNotice } from "./GitHubLoadNotice";
import { ScheduleEditor } from "./ScheduleEditor";

interface AutomationFormProps {
  initialValues?: {
    name?: string;
    prompt?: string;
    repositorySelection?: RepositorySelection;
    cronExpression?: string;
    timezone?: string;
    enabled?: boolean;
  };
  isSubmitting: boolean;
  submitLabel: string;
  fieldError?: {
    attr: string | null;
    message: string | null;
  } | null;
  generalError?: string | null;
  onSubmit: (values: CreateTaskAutomationOptions) => Promise<void> | void;
  onCancel?: () => void;
  repositoryRequired?: boolean;
  initialPromptMode?: "edit" | "preview";
  /** When true, suppress the built-in Cancel + Submit row. The parent
   *  screen is then responsible for rendering its own footer and
   *  triggering submission via `submitRef`. Used by screens that want a
   *  floating action button anchored to the screen instead of an inline
   *  footer that scrolls with the form. */
  hideFooter?: boolean;
  /** Mutable ref that the form populates with its internal submit handler.
   *  Lets a parent screen trigger validation+submission from a button
   *  rendered outside the form's tree (e.g. a screen-anchored FAB).
   *  Only meaningful alongside `hideFooter`. */
  submitRef?: MutableRefObject<(() => void) | null>;
  /** Fires whenever the form's derived `canSubmit` flag changes, so the
   *  parent can mirror the disabled/enabled state on an external button. */
  onCanSubmitChange?: (canSubmit: boolean) => void;
}

export function AutomationForm({
  initialValues,
  isSubmitting,
  submitLabel,
  fieldError,
  generalError,
  onSubmit,
  onCancel,
  repositoryRequired = true,
  initialPromptMode = "edit",
  hideFooter = false,
  submitRef,
  onCanSubmitChange,
}: AutomationFormProps) {
  const themeColors = useThemeColors();
  const {
    error,
    hasGithubIntegration,
    repositoryOptions,
    repositoryWarning,
    isLoading,
    isRefreshingInBackground,
    refetch,
  } = useIntegrations({ enabled: repositoryRequired });

  const [name, setName] = useState(initialValues?.name ?? "");
  const [prompt, setPrompt] = useState(initialValues?.prompt ?? "");
  const [timezone, setTimezone] = useState(initialValues?.timezone ?? "UTC");
  const [enabled, setEnabled] = useState(initialValues?.enabled ?? true);
  const [repositorySelection, setRepositorySelection] =
    useState<RepositorySelection>(
      initialValues?.repositorySelection ?? {
        integrationId: null,
        repository: null,
      },
    );
  const [scheduleDraft, setScheduleDraft] = useState<AutomationScheduleDraft>(
    initialValues?.cronExpression
      ? parseCronExpression(initialValues.cronExpression)
      : createDefaultScheduleDraft(),
  );
  const [hasEditedName, setHasEditedName] = useState(
    !!initialValues?.name?.trim(),
  );
  const [hasAttemptedSubmit, setHasAttemptedSubmit] = useState(false);
  const [promptMode, setPromptMode] = useState<"edit" | "preview">(
    initialPromptMode,
  );
  const [repoPickerOpen, setRepoPickerOpen] = useState(false);

  useEffect(() => {
    if (hasEditedName) {
      return;
    }

    setName(deriveAutomationName(prompt));
  }, [prompt, hasEditedName]);

  const validationErrors = useMemo(
    () => ({
      name:
        fieldError?.attr === "name"
          ? fieldError.message
          : hasAttemptedSubmit && !name.trim()
            ? "Name is required."
            : null,
      prompt:
        fieldError?.attr === "prompt"
          ? fieldError.message
          : hasAttemptedSubmit && !prompt.trim()
            ? "Prompt is required."
            : null,
      repository:
        fieldError?.attr === "repository"
          ? fieldError.message
          : repositoryRequired &&
              hasAttemptedSubmit &&
              !isRepositorySelectionComplete(repositorySelection)
            ? "Repository selection is required."
            : null,
      cronExpression:
        fieldError?.attr === "cron_expression" ? fieldError.message : null,
      timezone:
        fieldError?.attr === "timezone"
          ? fieldError.message
          : hasAttemptedSubmit && !timezone.trim()
            ? "Timezone is required."
            : null,
    }),
    [
      fieldError,
      hasAttemptedSubmit,
      name,
      prompt,
      repositorySelection,
      repositoryRequired,
      timezone,
    ],
  );

  const canSubmit =
    !!name.trim() &&
    !!prompt.trim() &&
    !!timezone.trim() &&
    (!repositoryRequired ||
      isRepositorySelectionComplete(repositorySelection)) &&
    !isSubmitting;
  const repositoryLoadBlocked =
    repositoryRequired && !!repositoryWarning && repositoryOptions.length === 0;

  const selectedRepositoryOption = useMemo(
    () => findRepositoryOption(repositoryOptions, repositorySelection),
    [repositoryOptions, repositorySelection],
  );

  // Disambiguate repos that exist across multiple integrations by appending
  // the integration label — matches the new-task screen's pill behaviour.
  const repositoryPillLabel = useMemo(() => {
    if (!selectedRepositoryOption) return "Select repository…";
    const sameRepoCount = repositoryOptions.filter(
      (option) => option.repository === selectedRepositoryOption.repository,
    ).length;
    return sameRepoCount > 1
      ? `${selectedRepositoryOption.repository} · ${selectedRepositoryOption.integrationLabel}`
      : selectedRepositoryOption.repository;
  }, [repositoryOptions, selectedRepositoryOption]);

  const handleSubmit = async () => {
    setHasAttemptedSubmit(true);
    if (!canSubmit) {
      return;
    }

    await onSubmit({
      name: name.trim(),
      prompt: prompt.trim(),
      repository: repositoryRequired
        ? (repositorySelection.repository ?? "")
        : "",
      github_integration: repositoryRequired
        ? repositorySelection.integrationId
        : null,
      cron_expression: buildCronExpression(scheduleDraft),
      timezone: timezone.trim(),
      enabled,
    });
  };

  // Expose the submit handler to a parent screen that wants to render its
  // own footer (e.g. a floating action button). We re-assign on every
  // render so the ref always points at the latest closure — the handler
  // captures current form state via the surrounding `useState` values.
  useEffect(() => {
    if (!submitRef) return;
    submitRef.current = handleSubmit;
    return () => {
      if (submitRef.current === handleSubmit) submitRef.current = null;
    };
  });

  // Mirror `canSubmit` to the parent so an external button can disable
  // itself the moment the form becomes invalid.
  useEffect(() => {
    onCanSubmitChange?.(canSubmit);
  }, [onCanSubmitChange, canSubmit]);

  if (repositoryRequired && isLoading && hasGithubIntegration === null) {
    return (
      <View className="items-center rounded-xl border border-gray-6 bg-gray-2 p-5">
        <ActivityIndicator size="small" color={themeColors.accent[9]} />
        <Text className="mt-2 text-gray-11 text-sm">
          Loading repositories...
        </Text>
      </View>
    );
  }

  if (repositoryRequired && (error || repositoryLoadBlocked)) {
    return (
      <GitHubLoadNotice
        message={
          error ?? repositoryWarning ?? "Could not load GitHub repositories."
        }
        onRetry={refetch}
      />
    );
  }

  if (repositoryRequired && hasGithubIntegration === false) {
    return (
      <GitHubConnectionPrompt
        scope="team"
        onConnected={refetch}
        title="Connect GitHub to create automations"
        description="Automations need repository access before they can run."
      />
    );
  }

  return (
    <View className="gap-4">
      {/* 1. Name — first config field. Auto-populates from the prompt until
          the user edits it manually. */}
      <View className="rounded-xl bg-gray-2 p-4">
        <Text
          className="mb-2 text-[11px] text-gray-9 uppercase"
          style={{ letterSpacing: 0.5 }}
        >
          Name
        </Text>
        <TextInput
          className="rounded-xl border border-gray-5 bg-background px-3.5 py-3 text-[15px] text-gray-12"
          placeholder="Daily PR review"
          placeholderTextColor={themeColors.gray[9]}
          value={name}
          onChangeText={(nextName) => {
            setHasEditedName(true);
            setName(nextName);
          }}
        />
        {validationErrors.name && (
          <Text className="mt-1 text-status-error text-xs">
            {validationErrors.name}
          </Text>
        )}
      </View>

      {/* 2. Repository — pill trigger + inline dropdown. Mirrors the
          new-task screen so the picker UX is consistent across the app. */}
      {repositoryRequired && (
        <View className="rounded-xl bg-gray-2 p-4">
          {repositoryWarning && (
            <View className="mb-3">
              <GitHubLoadNotice
                message={repositoryWarning}
                onRetry={refetch}
                tone="warning"
              />
            </View>
          )}
          <Text
            className="mb-2 text-[11px] text-gray-9 uppercase"
            style={{ letterSpacing: 0.5 }}
          >
            Repository
          </Text>
          <Pressable
            onPress={() => setRepoPickerOpen((prev) => !prev)}
            accessibilityRole="button"
            accessibilityLabel="Select repository"
            className={`flex-row items-center gap-2 rounded-xl border px-3.5 py-3 active:bg-gray-3 ${
              repoPickerOpen
                ? "border-accent-7 bg-accent-3"
                : "border-gray-5 bg-background"
            }`}
          >
            <GithubLogo
              size={16}
              color={
                selectedRepositoryOption
                  ? themeColors.gray[12]
                  : themeColors.gray[10]
              }
              weight={selectedRepositoryOption ? "fill" : "regular"}
            />
            <Text
              className={`flex-1 text-[15px] ${
                selectedRepositoryOption ? "text-gray-12" : "text-gray-9"
              }`}
              numberOfLines={1}
            >
              {repositoryPillLabel}
            </Text>
            <CaretDown
              size={12}
              color={themeColors.gray[10]}
              style={{
                transform: [{ rotate: repoPickerOpen ? "180deg" : "0deg" }],
              }}
            />
          </Pressable>

          {/* Inline dropdown — same component used by the new-task screen.
              Renders directly below the pill, so the form pushes content
              down rather than popping a modal. The picker self-unmounts
              once its exit animation finishes, so we only need the
              wrapper margin while it's open. */}
          <View className={repoPickerOpen ? "mt-2" : ""}>
            <RepositoryPickerInline
              open={repoPickerOpen}
              repositoryOptions={repositoryOptions}
              selected={selectedRepositoryOption}
              loading={isLoading && repositoryOptions.length === 0}
              isRefreshing={isRefreshingInBackground}
              // The automation form lives inside a parent ScrollView, so
              // the picker can't use its internal FlatList without
              // triggering RN's nested-VirtualizedList warning.
              nested
              onChange={(option) =>
                setRepositorySelection(toRepositorySelection(option))
              }
              onClose={() => setRepoPickerOpen(false)}
            />
          </View>

          {validationErrors.repository && (
            <Text className="mt-1 text-status-error text-xs">
              {validationErrors.repository}
            </Text>
          )}
        </View>
      )}

      {/* 3. Schedule */}
      <View className="rounded-xl bg-gray-2 p-4">
        <ScheduleEditor
          value={scheduleDraft}
          timezone={timezone}
          onChange={setScheduleDraft}
          onTimezoneChange={setTimezone}
        />
        {(validationErrors.cronExpression || validationErrors.timezone) && (
          <Text className="mt-1 text-status-error text-xs">
            {validationErrors.cronExpression || validationErrors.timezone}
          </Text>
        )}
      </View>

      {/* 4. Enabled */}
      <View className="flex-row items-center justify-between rounded-xl bg-gray-2 px-4 py-4">
        <View className="flex-1 pr-3">
          <Text className="font-semibold text-[15px] text-gray-12">
            Enabled
          </Text>
          <Text className="mt-1 text-gray-9 text-xs">
            Turn this off to pause scheduled runs without deleting it.
          </Text>
        </View>
        <Switch value={enabled} onValueChange={setEnabled} />
      </View>

      {/* 5. Prompt — the "skill" content. Placed last so the configuration
          (name, repo, schedule, enabled) is visible above the fold and the
          potentially-long prompt sits at the bottom for editing/preview. */}
      <View className="rounded-xl bg-gray-2 p-4">
        <Text
          className="mb-2 text-[11px] text-gray-9 uppercase"
          style={{ letterSpacing: 0.5 }}
        >
          Prompt
        </Text>
        <View className="mb-2 flex-row gap-2">
          {(["edit", "preview"] as const).map((mode) => {
            const active = promptMode === mode;

            return (
              <Pressable
                key={mode}
                onPress={() => setPromptMode(mode)}
                className={`rounded-lg border px-3 py-2 ${
                  active
                    ? "border-accent-9 bg-accent-3"
                    : "border-gray-5 bg-background"
                }`}
              >
                <Text
                  className={`font-medium text-[13px] ${
                    active ? "text-accent-11" : "text-gray-11"
                  }`}
                >
                  {mode === "edit" ? "Edit" : "Preview"}
                </Text>
              </Pressable>
            );
          })}
        </View>
        {promptMode === "edit" ? (
          <TextInput
            className="min-h-[128px] rounded-xl border border-gray-5 bg-background px-3.5 py-3 text-[15px] text-gray-12"
            placeholder="What should this automation ask the agent to do?"
            placeholderTextColor={themeColors.gray[9]}
            value={prompt}
            onChangeText={setPrompt}
            multiline
            textAlignVertical="top"
          />
        ) : (
          <View className="min-h-[128px] rounded-xl border border-gray-5 bg-background px-3.5 py-3">
            {prompt.trim() ? (
              <MarkdownText content={prompt} />
            ) : (
              <Text className="text-gray-9 text-sm">
                Nothing to preview yet.
              </Text>
            )}
          </View>
        )}
        {validationErrors.prompt && (
          <Text className="mt-1 text-status-error text-xs">
            {validationErrors.prompt}
          </Text>
        )}
      </View>

      {generalError && (
        <View className="rounded-xl bg-status-error/10 px-4 py-3">
          <Text className="text-sm text-status-error">{generalError}</Text>
        </View>
      )}

      {!hideFooter && (
        <View className="flex-row gap-3">
          {onCancel && (
            <Pressable
              onPress={onCancel}
              className="flex-1 rounded-xl border border-gray-6 bg-gray-2 py-3"
            >
              <Text className="text-center font-medium text-gray-12">
                Cancel
              </Text>
            </Pressable>
          )}
          <Pressable
            onPress={handleSubmit}
            disabled={!canSubmit}
            className={`rounded-xl py-3 ${
              onCancel ? "flex-1" : ""
            } ${canSubmit ? "bg-accent-9" : "bg-gray-3"}`}
          >
            {isSubmitting ? (
              <ActivityIndicator
                size="small"
                color={themeColors.accent.contrast}
              />
            ) : (
              <Text
                className={`text-center font-medium ${
                  canSubmit ? "text-accent-contrast" : "text-gray-9"
                }`}
              >
                {submitLabel}
              </Text>
            )}
          </Pressable>
        </View>
      )}
    </View>
  );
}
