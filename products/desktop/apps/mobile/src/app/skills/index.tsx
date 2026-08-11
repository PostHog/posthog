import { FloatingScreenHeader } from "@components/FloatingScreenHeader";
import { Text } from "@components/text";
import type { LlmSkillListItem } from "@posthog/api-client/posthog-client";
import { useRouter } from "expo-router";
import { BookOpen } from "phosphor-react-native";
import { useMemo, useState } from "react";
import {
  ActivityIndicator,
  FlatList,
  Pressable,
  RefreshControl,
  TextInput,
  View,
} from "react-native";
import { useSkillStoreSkills } from "@/features/tasks/skills/hooks";
import {
  filterSkills,
  skillCategoryLabel,
  skillVersionLabel,
  sortSkillsForDisplay,
} from "@/features/tasks/skills/skillPresentation";
import { useScreenInsets } from "@/hooks/useScreenInsets";
import { useThemeColors } from "@/lib/theme";

export default function SkillsScreen() {
  const themeColors = useThemeColors();
  const { insets, bottom } = useScreenInsets();
  const router = useRouter();
  const skillsQuery = useSkillStoreSkills();
  const [search, setSearch] = useState("");

  const skills = useMemo(
    () => sortSkillsForDisplay(skillsQuery.data ?? []),
    [skillsQuery.data],
  );
  const visible = useMemo(() => filterSkills(skills, search), [skills, search]);

  return (
    <View className="flex-1 bg-background">
      <FloatingScreenHeader title="Skills" />

      <View className="flex-1" style={{ paddingTop: insets.top + 60 }}>
        {skillsQuery.isPending ? (
          <View className="flex-1 items-center justify-center">
            <ActivityIndicator color={themeColors.accent[9]} />
          </View>
        ) : skillsQuery.isError ? (
          <SkillsError
            message={skillsQuery.error.message}
            onRetry={() => void skillsQuery.refetch()}
          />
        ) : (
          <FlatList
            data={visible}
            keyExtractor={(skill) => skill.id}
            ListHeaderComponent={
              skills.length > 0 ? (
                <View className="px-4 pb-3">
                  <TextInput
                    value={search}
                    onChangeText={setSearch}
                    placeholder="Search skills"
                    placeholderTextColor={themeColors.gray[9]}
                    autoCapitalize="none"
                    autoCorrect={false}
                    accessibilityLabel="Search skills"
                    className="rounded-lg border border-gray-6 bg-gray-2 px-3 py-2 text-[14px] text-gray-12"
                  />
                </View>
              ) : null
            }
            renderItem={({ item }) => (
              <SkillRow
                skill={item}
                onPress={() =>
                  router.push(`/skills/${encodeURIComponent(item.name)}`)
                }
              />
            )}
            ListEmptyComponent={
              search.trim() ? <NoMatches query={search} /> : <SkillsEmpty />
            }
            refreshControl={
              <RefreshControl
                refreshing={skillsQuery.isRefetching}
                onRefresh={() => void skillsQuery.refetch()}
                tintColor={themeColors.accent[9]}
              />
            }
            contentContainerStyle={{ paddingBottom: bottom("default") }}
          />
        )}
      </View>
    </View>
  );
}

function SkillRow({
  skill,
  onPress,
}: {
  skill: LlmSkillListItem;
  onPress: () => void;
}) {
  const category = skillCategoryLabel(skill.category);
  return (
    <Pressable
      accessibilityRole="button"
      onPress={onPress}
      className="mx-4 mb-2 rounded-xl border border-gray-6 bg-gray-1 px-4 py-3 active:opacity-80"
    >
      <View className="flex-row items-center gap-2">
        <Text
          className="flex-1 font-semibold text-[15px] text-gray-12"
          numberOfLines={1}
        >
          {skill.name}
        </Text>
        {category ? (
          <Text className="rounded bg-gray-3 px-1.5 py-0.5 text-[10px] text-gray-10 uppercase">
            {category}
          </Text>
        ) : null}
        <Text className="text-[11px] text-gray-9">
          {skillVersionLabel(skill)}
        </Text>
      </View>
      {skill.description ? (
        <Text className="mt-1.5 text-[13px] text-gray-11" numberOfLines={2}>
          {skill.description}
        </Text>
      ) : null}
    </Pressable>
  );
}

function SkillsError({
  message,
  onRetry,
}: {
  message: string;
  onRetry: () => void;
}) {
  return (
    <View className="items-center px-8 py-16">
      <Text className="mb-4 text-center text-[13px] text-status-error leading-snug">
        Couldn't load team skills. {message}
      </Text>
      <Pressable
        onPress={onRetry}
        className="rounded-lg bg-gray-3 px-4 py-2 active:opacity-80"
      >
        <Text className="font-medium text-[14px] text-gray-12">Retry</Text>
      </Pressable>
    </View>
  );
}

function NoMatches({ query }: { query: string }) {
  return (
    <View className="items-center px-8 py-16">
      <Text className="text-center text-[13px] text-gray-10">
        No skills match "{query.trim()}".
      </Text>
    </View>
  );
}

function SkillsEmpty() {
  const themeColors = useThemeColors();
  return (
    <View className="items-center px-8 py-16">
      <View className="mb-4 h-12 w-12 items-center justify-center rounded-full bg-gray-3">
        <BookOpen size={22} color={themeColors.gray[11]} weight="bold" />
      </View>
      <Text className="mb-1 font-semibold text-[16px] text-gray-12">
        No team skills yet
      </Text>
      <Text className="text-center text-[13px] text-gray-10 leading-snug">
        Skills are reusable methods your team shares with the agent. Once one is
        created it appears here.
      </Text>
    </View>
  );
}
