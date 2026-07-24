import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useRef } from "react";
import { InteractionManager, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { AutomationList } from "@/features/tasks/components/AutomationList";
import { FloatingAutomationsHeader } from "@/features/tasks/components/FloatingAutomationsHeader";
import { FloatingNewAutomationButton } from "@/features/tasks/components/FloatingNewAutomationButton";
import { useAutomations } from "@/features/tasks/hooks/useAutomations";

export default function AutomationsScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const readyRef = useRef(true);
  const { automations } = useAutomations();
  const hasAutomations = automations.length > 0;

  useFocusEffect(
    useCallback(() => {
      const handle = InteractionManager.runAfterInteractions(() => {
        readyRef.current = true;
      });
      return () => {
        readyRef.current = false;
        handle.cancel();
      };
    }, []),
  );

  const handleCreateAutomation = useCallback(() => {
    if (!readyRef.current) return;
    readyRef.current = false;
    router.push("/automation");
  }, [router]);

  const handleAutomationPress = useCallback(
    (automationId: string) => {
      if (!readyRef.current) return;
      readyRef.current = false;
      router.push(`/automation/${automationId}`);
    },
    [router],
  );

  // Matches FloatingTasksHeader: top inset + 6 (top pad) + 40 (button) + 8
  // (bottom pad) plus a small visual buffer so rows don't hug the fade.
  const headerHeight = insets.top + 64;

  return (
    <View className="flex-1 bg-background">
      <AutomationList
        onAutomationPress={handleAutomationPress}
        onCreateAutomation={handleCreateAutomation}
        contentInsetTop={headerHeight}
      />

      <FloatingAutomationsHeader />

      {hasAutomations ? (
        <FloatingNewAutomationButton onPress={handleCreateAutomation} />
      ) : null}
    </View>
  );
}
