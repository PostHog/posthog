import { FloatingScreenHeader } from "@components/FloatingScreenHeader";
import { Text } from "@components/text";
import { useLocalSearchParams } from "expo-router";
import { CaretDown, CaretRight, File as FileIcon } from "phosphor-react-native";
import { useState } from "react";
import { ActivityIndicator, Pressable, ScrollView, View } from "react-native";
import { MarkdownText } from "@/features/chat";
import {
  useSkillStoreSkill,
  useSkillStoreSkillFile,
} from "@/features/tasks/skills/hooks";
import {
  skillCategoryLabel,
  skillVersionLabel,
} from "@/features/tasks/skills/skillPresentation";
import { useScreenInsets } from "@/hooks/useScreenInsets";
import { useThemeColors } from "@/lib/theme";

export default function SkillDetailScreen() {
  const { name } = useLocalSearchParams<{ name: string }>();
  const themeColors = useThemeColors();
  const { insets, bottom } = useScreenInsets();
  const skillQuery = useSkillStoreSkill(name ?? null);
  const skill = skillQuery.data;

  return (
    <View className="flex-1 bg-background">
      <FloatingScreenHeader title={name ?? "Skill"} />

      {skillQuery.isPending ? (
        <View
          className="flex-1 items-center justify-center"
          style={{ paddingTop: insets.top + 60 }}
        >
          <ActivityIndicator color={themeColors.accent[9]} />
        </View>
      ) : skillQuery.isError || !skill ? (
        <View
          className="flex-1 items-center px-8"
          style={{ paddingTop: insets.top + 80 }}
        >
          <Text className="text-center text-[13px] text-status-error leading-snug">
            Couldn't load this skill.{" "}
            {skillQuery.error?.message ?? "It may have been deleted."}
          </Text>
        </View>
      ) : (
        <ScrollView
          className="flex-1"
          contentContainerStyle={{
            paddingTop: insets.top + 60,
            paddingBottom: bottom("default"),
          }}
        >
          <View className="flex-row flex-wrap items-center gap-2 px-4">
            {skillCategoryLabel(skill.category) ? (
              <Text className="rounded bg-gray-3 px-1.5 py-0.5 text-[10px] text-gray-10 uppercase">
                {skillCategoryLabel(skill.category)}
              </Text>
            ) : null}
            <Text className="text-[11px] text-gray-9">
              {skillVersionLabel(skill)}
            </Text>
          </View>

          {skill.description ? (
            <Text className="mt-2 px-4 text-[14px] text-gray-11 leading-5">
              {skill.description}
            </Text>
          ) : null}

          <View className="mt-4 px-4">
            <MarkdownText content={skill.body ?? ""} disableRemoteImages />
          </View>

          {skill.files.length > 0 ? (
            <View className="mt-6 px-4">
              <Text className="mb-2 font-semibold text-[13px] text-gray-12">
                Files ({skill.files.length})
              </Text>
              {skill.files.map((file) => (
                <SkillFileRow
                  key={file.path}
                  skillName={skill.name}
                  path={file.path}
                />
              ))}
            </View>
          ) : null}
        </ScrollView>
      )}
    </View>
  );
}

/**
 * One companion file, collapsed by default. The manifest carries paths only, so
 * the contents are fetched on first expand and cached from there.
 */
function SkillFileRow({
  skillName,
  path,
}: {
  skillName: string;
  path: string;
}) {
  const themeColors = useThemeColors();
  const [expanded, setExpanded] = useState(false);
  const fileQuery = useSkillStoreSkillFile(
    expanded ? skillName : null,
    expanded ? path : null,
  );

  return (
    <View className="mb-1 rounded-md bg-gray-2">
      <Pressable
        onPress={() => setExpanded((value) => !value)}
        accessibilityRole="button"
        accessibilityLabel={path}
        accessibilityState={{ expanded }}
        className="flex-row items-center gap-2 px-2 py-2 active:opacity-70"
      >
        {expanded ? (
          <CaretDown size={12} color={themeColors.gray[11]} />
        ) : (
          <CaretRight size={12} color={themeColors.gray[11]} />
        )}
        <FileIcon size={14} color={themeColors.gray[11]} />
        <Text className="flex-1 text-[13px] text-gray-12" numberOfLines={1}>
          {path}
        </Text>
      </Pressable>

      {expanded ? (
        <View className="px-2 pb-2">
          {fileQuery.isPending ? (
            <ActivityIndicator size="small" color={themeColors.gray[11]} />
          ) : fileQuery.isError ? (
            <Text className="text-[12px] text-status-error">
              Couldn't load this file.
            </Text>
          ) : (
            <ScrollView horizontal showsHorizontalScrollIndicator={false}>
              <Text
                className="font-mono text-[12px] text-gray-11 leading-4"
                selectable
              >
                {fileQuery.data?.content ?? ""}
              </Text>
            </ScrollView>
          )}
        </View>
      ) : null}
    </View>
  );
}
