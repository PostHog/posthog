import { Pressable, StyleSheet, Text, View } from "react-native";
import { colors, fonts, radius } from "@/lib/theme";

function Radio({ on }: { on: boolean }) {
  return (
    <View style={[styles.radio, on && styles.radioOn]}>
      {on ? <View style={styles.radioDot} /> : null}
    </View>
  );
}

// One row in a sheet card: a menu row (value + chevron) or a radio option.
export function SheetRow({
  label,
  value,
  onPress,
  radio,
  trailing,
  first,
}: {
  label: string;
  value?: string;
  onPress?: () => void;
  radio?: boolean;
  trailing?: string;
  first?: boolean;
}) {
  return (
    <Pressable
      onPress={onPress}
      disabled={!onPress}
      style={({ pressed }) => [
        styles.row,
        !first && styles.rowDivider,
        pressed && { opacity: 0.5 },
      ]}
    >
      {radio !== undefined ? <Radio on={radio} /> : null}
      <Text style={[styles.label, radio && styles.labelOn]} numberOfLines={1}>
        {label}
      </Text>
      <View style={{ flex: 1 }} />
      {value ? <Text style={styles.value}>{value}</Text> : null}
      {trailing ? <Text style={styles.trailing}>{trailing}</Text> : null}
      {onPress && radio === undefined ? (
        <Text style={styles.chevron}>›</Text>
      ) : null}
    </Pressable>
  );
}

export const sheetStyles = StyleSheet.create({
  root: { flex: 1, backgroundColor: colors.bg },
  list: { padding: 18, paddingBottom: 40, gap: 14 },
  card: {
    backgroundColor: "#FFFFFF",
    borderRadius: radius.card,
    paddingHorizontal: 16,
  },
  section: { gap: 8 },
  sectionTitle: {
    fontFamily: fonts.sansSemi,
    fontSize: 12,
    letterSpacing: 1.2,
    textTransform: "uppercase",
    color: colors.inkMute,
    marginLeft: 6,
  },
  footnote: {
    fontFamily: fonts.sans,
    fontSize: 12,
    color: colors.inkMute,
    marginLeft: 6,
  },
});

const styles = StyleSheet.create({
  row: {
    flexDirection: "row",
    alignItems: "center",
    gap: 12,
    paddingVertical: 13,
  },
  rowDivider: {
    borderTopWidth: StyleSheet.hairlineWidth,
    borderTopColor: colors.line,
  },
  label: {
    fontFamily: fonts.sans,
    fontSize: 16,
    color: colors.ink,
    flexShrink: 1,
  },
  labelOn: { fontFamily: fonts.sansSemi },
  value: { fontFamily: fonts.sans, fontSize: 16, color: colors.inkMute },
  trailing: { fontFamily: fonts.sans, fontSize: 14, color: colors.inkMute },
  chevron: {
    fontSize: 20,
    lineHeight: 22,
    color: colors.inkMute,
    marginLeft: 2,
  },
  radio: {
    width: 20,
    height: 20,
    borderRadius: 10,
    borderWidth: 1.5,
    borderColor: colors.line,
    alignItems: "center",
    justifyContent: "center",
  },
  radioOn: { borderColor: colors.accent, backgroundColor: colors.accent },
  radioDot: {
    width: 8,
    height: 8,
    borderRadius: 4,
    backgroundColor: "#FFFFFF",
  },
});
