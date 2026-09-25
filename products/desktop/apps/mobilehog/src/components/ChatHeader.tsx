import { useNavigation, useRouter } from "expo-router";
import { StyleSheet, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { GlassCircleButton } from "@/components/Glass";
import { MenuIcon, NewChatIcon } from "@/components/Icons";

interface ChatHeaderProps {
  showNewChat?: boolean;
}

export function ChatHeader({ showNewChat = true }: ChatHeaderProps) {
  const navigation = useNavigation<{ openDrawer: () => void }>();
  const router = useRouter();
  const insets = useSafeAreaInsets();
  return (
    <View
      style={[styles.root, { paddingTop: insets.top + 6 }]}
      pointerEvents="box-none"
    >
      <GlassCircleButton onPress={() => navigation.openDrawer()}>
        <MenuIcon />
      </GlassCircleButton>
      <View style={{ flex: 1 }} pointerEvents="none" />
      {showNewChat ? (
        <GlassCircleButton onPress={() => router.replace("/(drawer)")}>
          <NewChatIcon />
        </GlassCircleButton>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    position: "absolute",
    top: 0,
    left: 0,
    right: 0,
    zIndex: 10,
    flexDirection: "row",
    alignItems: "center",
    paddingHorizontal: 16,
  },
});
