import { Text } from "@components/text";
import { Pressable, TextInput, View } from "react-native";
import {
  type AutomationScheduleDraft,
  type AutomationScheduleMode,
  buildCronExpression,
  sanitizeHour,
  sanitizeMinute,
  WEEKDAY_OPTIONS,
} from "../utils/automationSchedule";

interface ScheduleEditorProps {
  value: AutomationScheduleDraft;
  timezone: string;
  onChange: (value: AutomationScheduleDraft) => void;
  onTimezoneChange: (timezone: string) => void;
}

const MODE_OPTIONS: Array<{
  value: AutomationScheduleMode;
  label: string;
}> = [
  { value: "hourly", label: "Hourly" },
  { value: "daily", label: "Daily" },
  { value: "weekdays", label: "Weekdays" },
  { value: "weekly", label: "Weekly" },
  { value: "custom", label: "Custom" },
];

export function ScheduleEditor({
  value,
  timezone,
  onChange,
  onTimezoneChange,
}: ScheduleEditorProps) {
  const updateDraft = (updates: Partial<AutomationScheduleDraft>) => {
    const nextDraft = {
      ...value,
      ...updates,
    };

    onChange({
      ...nextDraft,
      rawCron:
        nextDraft.mode === "custom"
          ? nextDraft.rawCron
          : buildCronExpression(nextDraft),
    });
  };

  return (
    <View>
      <Text
        className="mb-3 text-[11px] text-gray-9 uppercase"
        style={{ letterSpacing: 0.5 }}
      >
        Schedule
      </Text>

      <View className="mb-3 flex-row flex-wrap gap-2">
        {MODE_OPTIONS.map((option) => {
          const isSelected = value.mode === option.value;
          return (
            <Pressable
              key={option.value}
              onPress={() => updateDraft({ mode: option.value })}
              className={`rounded-xl border px-3 py-2 ${
                isSelected
                  ? "border-accent-8 bg-accent-3"
                  : "border-gray-5 bg-background"
              }`}
            >
              <Text
                className={`text-sm ${
                  isSelected ? "text-accent-11" : "text-gray-11"
                }`}
              >
                {option.label}
              </Text>
            </Pressable>
          );
        })}
      </View>

      {value.mode === "custom" ? (
        <TextInput
          className="mb-3 rounded-xl border border-gray-5 bg-background px-3.5 py-3 text-[15px] text-gray-12"
          placeholder="0 9 * * 1-5"
          value={value.rawCron}
          onChangeText={(rawCron) => onChange({ ...value, rawCron })}
          autoCapitalize="none"
          autoCorrect={false}
        />
      ) : (
        <>
          {value.mode === "hourly" ? (
            <View className="mb-3">
              <Text className="mb-1 text-gray-9 text-xs">
                Minute past the hour
              </Text>
              <TextInput
                className="rounded-xl border border-gray-5 bg-background px-3.5 py-3 text-[15px] text-gray-12"
                placeholder="00"
                value={value.minute}
                onChangeText={(minute) =>
                  updateDraft({ minute: sanitizeMinute(minute) })
                }
                keyboardType="number-pad"
              />
            </View>
          ) : (
            <View className="mb-3 flex-row gap-3">
              <View className="flex-1">
                <Text className="mb-1 text-gray-9 text-xs">Hour</Text>
                <TextInput
                  className="rounded-xl border border-gray-5 bg-background px-3.5 py-3 text-[15px] text-gray-12"
                  placeholder="09"
                  value={value.hour}
                  onChangeText={(hour) =>
                    updateDraft({ hour: sanitizeHour(hour) })
                  }
                  keyboardType="number-pad"
                />
              </View>
              <View className="flex-1">
                <Text className="mb-1 text-gray-9 text-xs">Minute</Text>
                <TextInput
                  className="rounded-xl border border-gray-5 bg-background px-3.5 py-3 text-[15px] text-gray-12"
                  placeholder="00"
                  value={value.minute}
                  onChangeText={(minute) =>
                    updateDraft({ minute: sanitizeMinute(minute) })
                  }
                  keyboardType="number-pad"
                />
              </View>
            </View>
          )}

          {value.mode === "weekly" && (
            <View className="mb-3">
              <Text className="mb-2 text-gray-9 text-xs">Day</Text>
              <View className="flex-row flex-wrap gap-2">
                {WEEKDAY_OPTIONS.map((option) => {
                  const isSelected = value.weekday === option.value;
                  return (
                    <Pressable
                      key={option.value}
                      onPress={() => updateDraft({ weekday: option.value })}
                      className={`rounded-xl border px-3 py-2 ${
                        isSelected
                          ? "border-accent-8 bg-accent-3"
                          : "border-gray-5 bg-background"
                      }`}
                    >
                      <Text
                        className={`text-sm ${
                          isSelected ? "text-accent-11" : "text-gray-11"
                        }`}
                      >
                        {option.label}
                      </Text>
                    </Pressable>
                  );
                })}
              </View>
            </View>
          )}
        </>
      )}

      <View className="mb-3">
        <Text className="mb-1 text-gray-9 text-xs">Timezone</Text>
        <TextInput
          className="rounded-xl border border-gray-5 bg-background px-3.5 py-3 text-[15px] text-gray-12"
          placeholder="Europe/London"
          value={timezone}
          onChangeText={onTimezoneChange}
          autoCapitalize="none"
          autoCorrect={false}
        />
      </View>
    </View>
  );
}
