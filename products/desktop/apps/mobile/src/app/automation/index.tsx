import { Stack, useRouter } from "expo-router";
import { ScrollView, View } from "react-native";
import { Text } from "@/components/text";
import { AutomationSkillChooser } from "@/features/tasks/components/AutomationSkillChooser";
import { useThemeColors } from "@/lib/theme";

export default function AutomationTemplateScreen() {
  const router = useRouter();
  const themeColors = useThemeColors();

  return (
    <>
      <Stack.Screen
        options={{
          headerShown: true,
          headerTitle: "Create automation",
          headerStyle: { backgroundColor: themeColors.background },
          headerTintColor: themeColors.gray[12],
          presentation: "modal",
        }}
      />
      <ScrollView
        className="flex-1 bg-background px-4 pt-4"
        contentContainerStyle={{ paddingBottom: 40 }}
      >
        <View className="gap-4">
          <View>
            <Text className="font-semibold text-[16px] text-gray-12">
              Choose how to start
            </Text>
            <Text className="mt-2 text-gray-11 text-sm">
              Start from scratch, or pick a shared skill from the store and
              tailor it before saving.
            </Text>
          </View>

          <AutomationSkillChooser
            onSelectSkill={(skillName) =>
              router.push({
                pathname: "/automation/create",
                params: { skillName },
              })
            }
            onCreateCustom={() => router.push("/automation/create")}
          />
        </View>
      </ScrollView>
    </>
  );
}
