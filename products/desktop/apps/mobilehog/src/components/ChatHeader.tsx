import { useNavigation } from "expo-router";
import { StyleSheet, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { GlassCircleButton } from "@/components/Glass";
import { MenuIcon } from "@/components/Icons";

interface ChatHeaderProps {
  inline?: boolean;
}

export function ChatHeader({ inline = false }: ChatHeaderProps) {
  const navigation = useNavigation<{ openDrawer: () => void }>();
  const insets = useSafeAreaInsets();
  return (
    <View
      style={[
        styles.root,
        inline && styles.inline,
        { paddingTop: insets.top + 6 },
      ]}
      pointerEvents="box-none"
    >
      <GlassCircleButton onPress={() => navigation.openDrawer()}>
        <MenuIcon />
      </GlassCircleButton>
      <View style={{ flex: 1 }} pointerEvents="none" />
    </View>
  );
}

const styles = StyleSheet.create({
  inline: { position: "relative", paddingBottom: 12 },
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
