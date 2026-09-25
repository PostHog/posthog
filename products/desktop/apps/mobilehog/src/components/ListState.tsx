import type { ReactNode } from "react";
import {
  ActivityIndicator,
  Pressable,
  StyleSheet,
  Text,
  View,
} from "react-native";
import { colors, fonts, radius } from "@/lib/theme";

export function ListState({
  title,
  description,
  icon,
  loading = false,
  action,
}: {
  title: string;
  description?: string;
  icon?: ReactNode;
  loading?: boolean;
  action?: { label: string; onPress: () => void; disabled?: boolean };
}) {
  return (
    <View style={styles.root}>
      {loading ? (
        <ActivityIndicator color={colors.inkMute} />
      ) : icon ? (
        <View style={styles.icon} accessible={false}>
          {icon}
        </View>
      ) : null}
      <Text style={styles.title}>{title}</Text>
      {description ? (
        <Text style={styles.description}>{description}</Text>
      ) : null}
      {action ? (
        <Pressable
          accessibilityRole="button"
          onPress={action.onPress}
          disabled={action.disabled}
          style={({ pressed }) => [
            styles.action,
            (pressed || action.disabled) && { opacity: 0.5 },
          ]}
        >
          <Text style={styles.actionText}>{action.label}</Text>
        </Pressable>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  root: {
    flex: 1,
    justifyContent: "center",
    alignItems: "center",
    paddingHorizontal: 24,
    paddingVertical: 40,
    gap: 12,
  },
  icon: {
    width: 56,
    height: 56,
    borderRadius: 28,
    backgroundColor: colors.fill,
    alignItems: "center",
    justifyContent: "center",
    marginBottom: 4,
  },
  title: {
    fontFamily: fonts.sansSemi,
    fontSize: 22,
    color: colors.ink,
    textAlign: "center",
  },
  description: {
    fontFamily: fonts.sans,
    fontSize: 16,
    lineHeight: 22,
    color: colors.inkSoft,
    textAlign: "center",
    maxWidth: 300,
  },
  action: {
    backgroundColor: colors.fill,
    borderRadius: radius.pill,
    paddingHorizontal: 20,
    paddingVertical: 12,
    marginTop: 4,
  },
  actionText: { fontFamily: fonts.sansSemi, fontSize: 15, color: colors.ink },
});
