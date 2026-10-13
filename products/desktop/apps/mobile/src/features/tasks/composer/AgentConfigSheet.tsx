import { Text } from "@components/text";
import type { SupportedReasoningEffort } from "@posthog/shared";
import {
  ArrowCounterClockwise,
  CaretDown,
  Check,
  Lightning,
} from "phosphor-react-native";
import { Fragment, useState } from "react";
import { Pressable, ScrollView, Switch, View } from "react-native";
import { SheetContainer } from "@/components/SheetContainer";
import { useThemeColors } from "@/lib/theme";
import type { AgentPreset, ContextWindow, MobileModelGroup } from "./options";

interface AgentConfigSheetProps {
  open: boolean;
  onClose: () => void;
  model: string;
  reasoning: SupportedReasoningEffort;
  contextWindow: ContextWindow;
  fastMode: boolean;
  presets: AgentPreset[];
  reasoningOptions: ReadonlyArray<{ value: string; name: string }>;
  modelGroups: MobileModelGroup[];
  fastModeAvailable: boolean;
  contextWindowAvailable: boolean;
  onSelectPreset: (preset: AgentPreset) => void;
  onModelChange: (model: string) => void;
  onReasoningChange: (value: SupportedReasoningEffort) => void;
  onFastModeChange: (enabled: boolean) => void;
  onContextWindowChange: (value: ContextWindow) => void;
  onReset: () => void;
}

function SectionLabel({ children }: { children: string }) {
  return (
    <Text className="px-4 pt-4 pb-1 font-medium text-[12px] text-gray-10 uppercase tracking-wide">
      {children}
    </Text>
  );
}

function GroupHeader({ children }: { children: string }) {
  return (
    <Text className="px-4 pt-3 pb-1 font-medium text-[11px] text-gray-10 uppercase tracking-wide">
      {children}
    </Text>
  );
}

function Row({
  label,
  description,
  selected,
  onPress,
}: {
  label: string;
  description?: string;
  selected: boolean;
  onPress: () => void;
}) {
  const themeColors = useThemeColors();
  return (
    <Pressable
      onPress={onPress}
      className="flex-row items-center gap-3 px-4 py-2.5 active:bg-gray-2"
    >
      <View className="min-w-0 flex-1">
        <Text className="text-[15px] text-gray-12">{label}</Text>
        {description ? (
          <Text className="mt-0.5 text-[12px] text-gray-10">{description}</Text>
        ) : null}
      </View>
      {selected ? (
        <Check size={16} color={themeColors.accent[9]} weight="bold" />
      ) : null}
    </Pressable>
  );
}

function Segmented<T extends string>({
  value,
  options,
  onChange,
}: {
  value: T;
  options: ReadonlyArray<{ value: T; label: string }>;
  onChange: (value: T) => void;
}) {
  return (
    <View className="mx-4 mt-1 mb-1 flex-row gap-1 rounded-lg bg-gray-3 p-1">
      {options.map((option) => {
        const active = option.value === value;
        return (
          <Pressable
            key={option.value}
            onPress={() => onChange(option.value)}
            className={`flex-1 items-center rounded-md py-1.5 ${
              active ? "bg-background" : "active:opacity-60"
            }`}
          >
            <Text
              className={`text-[13px] ${
                active ? "font-medium text-gray-12" : "text-gray-11"
              }`}
            >
              {option.label}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

export function AgentConfigSheet({
  open,
  onClose,
  model,
  reasoning,
  contextWindow,
  fastMode,
  presets,
  reasoningOptions,
  modelGroups,
  fastModeAvailable,
  contextWindowAvailable,
  onSelectPreset,
  onModelChange,
  onReasoningChange,
  onFastModeChange,
  onContextWindowChange,
  onReset,
}: AgentConfigSheetProps) {
  const themeColors = useThemeColors();
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const showGroupHeaders = modelGroups.length > 1;

  return (
    <SheetContainer open={open} onClose={onClose}>
      <View className="flex-row items-center justify-between px-4 pt-2 pb-1">
        <Text className="font-semibold text-[16px] text-gray-12">
          Model & reasoning
        </Text>
        {fastModeAvailable ? (
          <View className="flex-row items-center gap-2">
            <Lightning
              size={15}
              color={
                fastMode ? themeColors.status.warning : themeColors.gray[10]
              }
              weight={fastMode ? "fill" : "regular"}
            />
            <Text className="text-[13px] text-gray-11">Fast</Text>
            <Switch value={fastMode} onValueChange={onFastModeChange} />
          </View>
        ) : null}
      </View>

      <ScrollView className="max-h-[70vh]">
        {presets.length > 0 ? (
          <>
            <View className="flex-row items-center justify-between px-4 pt-3">
              <Text className="text-[12px] text-gray-10">Faster</Text>
              <Text className="text-[12px] text-gray-10">Smarter</Text>
            </View>
            {presets.map((preset) => {
              const selected =
                preset.model === model && preset.effort === reasoning;
              return (
                <Row
                  key={`${preset.model}:${preset.effort}`}
                  label={`${preset.modelLabel} · ${preset.effortLabel}`}
                  selected={selected}
                  onPress={() => onSelectPreset(preset)}
                />
              );
            })}
          </>
        ) : null}

        {contextWindowAvailable ? (
          <>
            <SectionLabel>Context window</SectionLabel>
            <Segmented
              value={contextWindow}
              onChange={onContextWindowChange}
              options={[
                { value: "200k", label: "200k" },
                { value: "1m", label: "1M" },
              ]}
            />
          </>
        ) : null}

        <Pressable
          onPress={() => setAdvancedOpen((prev) => !prev)}
          className="mt-4 flex-row items-center gap-1.5 px-4 py-2 active:opacity-60"
        >
          <CaretDown
            size={12}
            color={themeColors.gray[10]}
            style={{
              transform: [{ rotate: advancedOpen ? "0deg" : "-90deg" }],
            }}
          />
          <Text className="font-medium text-[13px] text-gray-11">Advanced</Text>
        </Pressable>

        {advancedOpen ? (
          <>
            <SectionLabel>Model</SectionLabel>
            {modelGroups.map((group) => (
              <Fragment key={group.key}>
                {showGroupHeaders ? (
                  <GroupHeader>{group.name}</GroupHeader>
                ) : null}
                {group.options.map((option) => (
                  <Row
                    key={option.value}
                    label={option.label}
                    description={
                      option.disabled ? "Upgrade required" : option.description
                    }
                    selected={option.value === model}
                    onPress={() => {
                      if (!option.disabled) onModelChange(option.value);
                    }}
                  />
                ))}
              </Fragment>
            ))}

            {reasoningOptions.length > 0 ? (
              <>
                <SectionLabel>Reasoning</SectionLabel>
                {reasoningOptions.map((option) => (
                  <Row
                    key={option.value}
                    label={option.name}
                    selected={option.value === reasoning}
                    onPress={() =>
                      onReasoningChange(
                        option.value as SupportedReasoningEffort,
                      )
                    }
                  />
                ))}
              </>
            ) : null}

            <Pressable
              onPress={onReset}
              className="mt-2 mb-2 flex-row items-center gap-2 px-4 py-3 active:bg-gray-2"
            >
              <ArrowCounterClockwise size={14} color={themeColors.gray[11]} />
              <Text className="text-[15px] text-gray-11">Reset to default</Text>
            </Pressable>
          </>
        ) : null}
      </ScrollView>
    </SheetContainer>
  );
}
