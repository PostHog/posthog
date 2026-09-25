import { Modal, Pressable, StyleSheet, Text, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { colors, fonts } from "@/lib/theme";

export interface SheetOption {
  label: string;
  selected?: boolean;
  disabled?: boolean;
  onPress: () => void;
}

export function OptionsSheet({
  title,
  options,
  onClose,
}: {
  title: string;
  options: SheetOption[];
  onClose: () => void;
}) {
  const insets = useSafeAreaInsets();
  return (
    <Modal transparent animationType="slide" onRequestClose={onClose}>
      <View style={styles.overlay}>
        <Pressable
          style={StyleSheet.absoluteFill}
          onPress={onClose}
          accessibilityLabel="Close menu"
          accessibilityRole="button"
        />
        <View
          accessibilityViewIsModal
          style={[styles.sheet, { paddingBottom: insets.bottom + 12 }]}
        >
          <Text style={styles.title}>{title}</Text>
          {options.map((option) => (
            <Pressable
              key={option.label}
              accessibilityRole="button"
              accessibilityState={{
                selected: option.selected,
                disabled: option.disabled,
              }}
              disabled={option.disabled}
              style={styles.option}
              onPress={() => {
                onClose();
                option.onPress();
              }}
            >
              <Text style={[styles.label, option.disabled && styles.disabled]}>
                {option.label}
              </Text>
              {option.selected ? <Text style={styles.check}>✓</Text> : null}
            </Pressable>
          ))}
          <Pressable
            accessibilityRole="button"
            onPress={onClose}
            style={styles.option}
          >
            <Text style={styles.check}>Cancel</Text>
          </Pressable>
        </View>
      </View>
    </Modal>
  );
}

const styles = StyleSheet.create({
  overlay: {
    flex: 1,
    justifyContent: "flex-end",
    backgroundColor: "rgba(0,0,0,0.35)",
  },
  sheet: {
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    backgroundColor: colors.surface,
    padding: 20,
  },
  title: {
    fontFamily: fonts.sansSemi,
    fontSize: 14,
    color: colors.inkSoft,
    paddingBottom: 12,
  },
  option: {
    minHeight: 48,
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-between",
    gap: 12,
  },
  label: {
    fontFamily: fonts.sansMedium,
    fontSize: 16,
    color: colors.ink,
    flexShrink: 1,
  },
  check: { fontFamily: fonts.sansMedium, fontSize: 16, color: colors.accent },
  disabled: { opacity: 0.4 },
});
