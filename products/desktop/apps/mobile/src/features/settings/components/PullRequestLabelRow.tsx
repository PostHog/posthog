import { Text } from "@components/text";
import {
  DEFAULT_PULL_REQUEST_LABEL,
  describePullRequestLabel,
  effectivePullRequestLabel,
  PULL_REQUEST_LABEL_MAX_LENGTH,
  type PullRequestLabelUpdate,
  parsePullRequestLabel,
  pullRequestLabelEnabled,
  pullRequestLabelFieldValue,
} from "@posthog/core/inbox/pullRequestLabel";
import { CaretRight } from "phosphor-react-native";
import { useState } from "react";
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  Switch,
  TextInput,
  View,
} from "react-native";
import { SheetContainer } from "@/components/SheetContainer";
import {
  useSignalTeamConfig,
  useUpdatePullRequestLabel,
} from "@/features/inbox/hooks/useSignalTeamConfig";
import { SettingsRow } from "@/features/settings/components/SettingsRow";
import { useThemeColors } from "@/lib/theme";

export function PullRequestLabelRow() {
  const themeColors = useThemeColors();
  const { data: config, isLoading, isError } = useSignalTeamConfig();
  const updateLabel = useUpdatePullRequestLabel();
  const [sheetOpen, setSheetOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);

  const enabled = pullRequestLabelEnabled(config);
  const savedValue = pullRequestLabelFieldValue(config);
  // A failed background refetch keeps the cached config while flipping isError,
  // so only the case with no cached config is a hard error.
  const showLoadError = isError && config === undefined;
  const rightLabel = showLoadError
    ? "—"
    : enabled
      ? effectivePullRequestLabel(config)
      : "Off";

  const openSheet = () => {
    setDraft(savedValue);
    setError(null);
    setSheetOpen(true);
  };

  const save = async (updates: PullRequestLabelUpdate, close: boolean) => {
    setError(null);
    try {
      await updateLabel.mutateAsync(updates);
      if (close) {
        setSheetOpen(false);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save the label.");
    }
  };

  const handleSave = () => {
    const parsed = parsePullRequestLabel(draft);
    if (!parsed.ok) {
      setError(parsed.error);
      return;
    }
    void save({ pull_request_label: parsed.value }, true);
  };

  return (
    <>
      <SettingsRow
        label="Label PRs on GitHub"
        description={
          showLoadError
            ? "Couldn't load the label. Try again later."
            : describePullRequestLabel(config)
        }
        onPress={openSheet}
        disabled={isLoading || showLoadError}
        rightSlot={
          <>
            <Text className="text-[14px] text-gray-11">{rightLabel}</Text>
            <CaretRight size={14} color={themeColors.gray[10]} />
          </>
        }
      />

      <PullRequestLabelSheet
        open={sheetOpen}
        enabled={enabled}
        draft={draft}
        error={error}
        isSaving={updateLabel.isPending}
        onChangeDraft={(text) => {
          setDraft(text);
          setError(null);
        }}
        onToggle={(checked) =>
          void save({ pull_request_label_enabled: checked }, false)
        }
        onClose={() => setSheetOpen(false)}
        onSave={handleSave}
      />
    </>
  );
}

interface PullRequestLabelSheetProps {
  open: boolean;
  enabled: boolean;
  draft: string;
  error: string | null;
  isSaving: boolean;
  onChangeDraft: (text: string) => void;
  onToggle: (checked: boolean) => void;
  onClose: () => void;
  onSave: () => void;
}

function PullRequestLabelSheet({
  open,
  enabled,
  draft,
  error,
  isSaving,
  onChangeDraft,
  onToggle,
  onClose,
  onSave,
}: PullRequestLabelSheetProps) {
  const themeColors = useThemeColors();

  return (
    <SheetContainer open={open} onClose={onClose}>
      <KeyboardAvoidingView
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        <View className="gap-3 px-4 pt-2 pb-2">
          <Text className="font-semibold text-[16px] text-gray-12">
            Label PRs on GitHub
          </Text>
          <Text className="text-[13px] text-gray-10 leading-snug">
            Add a label to every PR agents open, so you can find them in GitHub
            search and notification rules. PostHog creates the label if your
            repository does not have it.
          </Text>

          <View className="flex-row items-center justify-between gap-3">
            <Text className="text-[15px] text-gray-12">Add the label</Text>
            <Switch
              value={enabled}
              disabled={isSaving}
              onValueChange={onToggle}
            />
          </View>

          {enabled ? (
            <>
              <TextInput
                value={draft}
                onChangeText={onChangeDraft}
                autoCapitalize="none"
                autoCorrect={false}
                maxLength={PULL_REQUEST_LABEL_MAX_LENGTH}
                placeholder={DEFAULT_PULL_REQUEST_LABEL}
                placeholderTextColor={themeColors.gray[9]}
                editable={!isSaving}
                className="rounded-lg border border-gray-6 bg-gray-2 px-3 py-2.5 text-[15px] text-gray-12"
              />

              <Pressable
                onPress={onSave}
                disabled={isSaving}
                className={`flex-row items-center justify-center rounded-lg bg-accent-9 py-3 ${isSaving ? "opacity-60" : "active:opacity-80"}`}
              >
                {isSaving ? (
                  <ActivityIndicator size="small" color={themeColors.gray[1]} />
                ) : (
                  <Text className="font-semibold text-[15px] text-gray-1">
                    Save
                  </Text>
                )}
              </Pressable>
            </>
          ) : null}

          {error ? (
            <Text className="text-[12.5px] text-status-error">{error}</Text>
          ) : null}
        </View>
      </KeyboardAvoidingView>
    </SheetContainer>
  );
}
