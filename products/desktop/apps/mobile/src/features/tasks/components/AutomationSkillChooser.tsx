import { useMemo, useState } from "react";
import { ActivityIndicator, Pressable, TextInput, View } from "react-native";
import { Text } from "@/components/text";
import { useThemeColors } from "@/lib/theme";
import { useSkillStoreSkills } from "../skills/hooks";
import { AutomationSkillCard } from "./AutomationSkillCard";

interface AutomationSkillChooserProps {
  onCreateCustom: () => void;
  onSelectSkill: (skillName: string) => void;
}

export function AutomationSkillChooser({
  onCreateCustom,
  onSelectSkill,
}: AutomationSkillChooserProps) {
  const themeColors = useThemeColors();
  const { data, isLoading, error, refetch } = useSkillStoreSkills();
  const skills = data ?? [];
  const [search, setSearch] = useState("");
  const filteredSkills = useMemo(() => {
    const query = search.trim().toLowerCase();

    if (!query) {
      return skills;
    }

    return skills.filter(
      (skill) =>
        skill.name.toLowerCase().includes(query) ||
        skill.description?.toLowerCase().includes(query),
    );
  }, [search, skills]);

  return (
    <View className="gap-4">
      <Pressable
        accessibilityRole="button"
        onPress={onCreateCustom}
        className="rounded-xl border border-accent-6 bg-accent-2 px-4 py-4 active:opacity-80"
      >
        <Text className="font-semibold text-[15px] text-gray-12">
          Start from scratch
        </Text>
        <Text className="mt-2 text-gray-11 text-sm">
          Create a custom automation prompt and schedule it yourself.
        </Text>
      </Pressable>

      <View className="gap-2">
        <Text className="font-semibold text-[14px] text-gray-12">
          Skill store
        </Text>
        <Text className="text-gray-10 text-sm">
          Shared team skills you can use as automation starters.
        </Text>
      </View>

      {isLoading ? (
        <View className="items-center rounded-xl border border-gray-6 bg-gray-1 px-4 py-6">
          <ActivityIndicator size="small" color={themeColors.accent[9]} />
          <Text className="mt-3 text-gray-11 text-sm">Loading skills...</Text>
        </View>
      ) : error ? (
        <View className="rounded-xl border border-gray-6 bg-gray-1 px-4 py-4">
          <Text className="font-medium text-[15px] text-gray-12">
            Skills unavailable
          </Text>
          <Text className="mt-2 text-gray-11 text-sm">{error.message}</Text>
          <Pressable
            accessibilityRole="button"
            onPress={() => void refetch()}
            className="mt-4 self-start rounded-lg border border-gray-6 bg-gray-2 px-3 py-2"
          >
            <Text className="font-medium text-gray-12 text-sm">Try again</Text>
          </Pressable>
        </View>
      ) : skills.length === 0 ? (
        <View className="rounded-xl border border-gray-6 bg-gray-1 px-4 py-4">
          <Text className="font-medium text-[15px] text-gray-12">
            No skills available
          </Text>
          <Text className="mt-2 text-gray-11 text-sm">
            You can still start from scratch above and create a custom
            automation.
          </Text>
        </View>
      ) : (
        <>
          <TextInput
            className="rounded-xl border border-gray-5 bg-background px-3.5 py-3 text-[15px] text-gray-12"
            placeholder="Search skills"
            placeholderTextColor={themeColors.gray[9]}
            value={search}
            onChangeText={setSearch}
            autoCapitalize="none"
            autoCorrect={false}
            clearButtonMode="while-editing"
          />

          {filteredSkills.length === 0 ? (
            <View className="rounded-xl border border-gray-6 bg-gray-1 px-4 py-4">
              <Text className="font-medium text-[15px] text-gray-12">
                No matching skills
              </Text>
              <Text className="mt-2 text-gray-11 text-sm">
                {`No skills match "${search.trim()}" yet.`}
              </Text>
            </View>
          ) : (
            filteredSkills.map((skill) => (
              <AutomationSkillCard
                key={skill.name}
                skill={skill}
                onPress={onSelectSkill}
              />
            ))
          )}
        </>
      )}
    </View>
  );
}
