import { useRouter } from "expo-router";
import { StyleSheet, Text, View } from "react-native";
import { GlassCircleButton } from "@/components/Glass";
import { colors, fonts } from "@/lib/theme";

// Header for pages inside a form sheet: X on the root page, back chevron deeper.
export function SheetHeader({
  title,
  back,
}: {
  title: string;
  back?: boolean;
}) {
  const router = useRouter();
  return (
    <View style={styles.header}>
      <GlassCircleButton size={44} onPress={() => router.back()}>
        <Text style={styles.glyph}>{back ? "‹" : "×"}</Text>
      </GlassCircleButton>
      <Text style={styles.title}>{title}</Text>
      <View style={{ width: 44 }} />
    </View>
  );
}

const styles = StyleSheet.create({
  header: {
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    marginBottom: 4,
  },
  glyph: { fontSize: 28, lineHeight: 30, color: colors.ink, marginTop: -3 },
  title: { fontFamily: fonts.sansSemi, fontSize: 17, color: colors.ink },
});
