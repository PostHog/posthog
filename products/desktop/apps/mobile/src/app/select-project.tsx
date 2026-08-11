import { Text } from "@components/text";
import { router, useLocalSearchParams } from "expo-router";
import { CaretRight, MagnifyingGlass } from "phosphor-react-native";
import { useMemo, useState } from "react";
import { Alert, FlatList, Pressable, TextInput, View } from "react-native";
import { SafeAreaView } from "react-native-safe-area-context";
import { useAuthStore, useProjectsQuery } from "@/features/auth";
import { resolvePostLoginTarget } from "@/features/auth/lib/postLoginTarget";
import { useScreenInsets } from "@/hooks/useScreenInsets";
import { useThemeColors } from "@/lib/theme";

interface ProjectOption {
  id: number;
  name: string;
}

/** Below this a list is short enough to scan, so search is just clutter. */
const SEARCHABLE_PROJECT_COUNT = 6;

/**
 * Post-login project picker. Shown only when the token is scoped to more than
 * one project, so the app never silently lands on `scoped_teams[0]`. Settings
 * keeps the compact `ProjectSelectSheet` for switching later; this is the
 * onboarding-sized version, with search for accounts scoped to dozens of
 * projects.
 */
export default function SelectProjectScreen() {
  const themeColors = useThemeColors();
  const screenInsets = useScreenInsets();
  const { next } = useLocalSearchParams<{ next?: string }>();
  const { scopedTeams, setProjectId } = useAuthStore();
  const { data: projects } = useProjectsQuery();
  const [search, setSearch] = useState("");

  const options = useMemo<ProjectOption[]>(
    () =>
      scopedTeams.map((id) => ({
        id,
        name: projects?.find((project) => project.id === id)?.name ?? "",
      })),
    [scopedTeams, projects],
  );

  const visibleOptions = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return options;
    return options.filter(
      (option) =>
        option.name.toLowerCase().includes(needle) ||
        String(option.id).includes(needle),
    );
  }, [options, search]);

  const handleSelect = (projectId: number) => {
    if (!setProjectId(projectId)) {
      Alert.alert(
        "Can't switch project",
        "Your login isn't authorized for that project. Log out and back in to grant access to it.",
      );
      return;
    }
    router.replace(resolvePostLoginTarget(next));
  };

  return (
    <SafeAreaView className="flex-1 bg-gray-1" edges={["top", "left", "right"]}>
      <View className="px-6 pt-8 pb-5">
        <Text className="mb-2 font-semibold text-2xl text-gray-12">
          Choose a project
        </Text>
        <Text className="text-[15px] text-gray-11 leading-snug">
          Tasks, automations and reports are scoped to one project. You can
          switch any time in Settings.
        </Text>
      </View>

      {options.length > SEARCHABLE_PROJECT_COUNT ? (
        <View className="px-6 pb-4">
          <View className="flex-row items-center gap-2 rounded-lg border border-gray-5 bg-card px-3 py-2">
            <MagnifyingGlass size={16} color={themeColors.gray[10]} />
            <TextInput
              value={search}
              onChangeText={setSearch}
              placeholder="Search projects"
              placeholderTextColor={themeColors.gray[10]}
              className="flex-1 text-[14px] text-gray-12"
              autoCapitalize="none"
              autoCorrect={false}
            />
          </View>
        </View>
      ) : null}

      <FlatList
        data={visibleOptions}
        keyExtractor={(option) => String(option.id)}
        keyboardShouldPersistTaps="handled"
        keyboardDismissMode="on-drag"
        contentContainerStyle={{
          paddingHorizontal: 24,
          paddingBottom: screenInsets.bottom(),
        }}
        ListEmptyComponent={
          search.trim() ? (
            <Text className="px-1 py-6 text-[14px] text-gray-11">
              No projects match “{search.trim()}”.
            </Text>
          ) : null
        }
        renderItem={({ item }) => (
          <Pressable
            onPress={() => handleSelect(item.id)}
            className="mb-2 flex-row items-center gap-3 rounded-xl border border-gray-5 bg-card px-4 py-3.5 active:bg-gray-3"
            accessibilityRole="button"
            accessibilityLabel={`Choose ${item.name || `Project ${item.id}`}`}
          >
            <View className="min-w-0 flex-1">
              <Text
                className="font-medium text-[15px] text-gray-12"
                numberOfLines={1}
              >
                {item.name || `Project ${item.id}`}
              </Text>
              <Text className="mt-0.5 text-[12px] text-gray-10">
                ID {item.id}
              </Text>
            </View>
            <CaretRight size={16} color={themeColors.gray[10]} />
          </Pressable>
        )}
      />
    </SafeAreaView>
  );
}
