import type { ReactNode } from "react";
import { Modal, Pressable, View, type ViewStyle } from "react-native";
import {
  type BottomGapVariant,
  useScreenInsets,
} from "@/hooks/useScreenInsets";

const SHEET_SHADOW = {
  shadowColor: "#000",
  shadowOpacity: 0.15,
  shadowRadius: 20,
  shadowOffset: { width: 0, height: -4 },
  elevation: 12,
} as const;

interface SheetContainerProps {
  open: boolean;
  onClose: () => void;
  children: ReactNode;
  /**
   * Bottom padding gap above the safe-area inset. Defaults to "compact"
   * because that is the gap both legacy sheets (SelectSheet, AttachmentSheet)
   * inherited — deliberately not BOTTOM_GAP's own "default" (24). Pass
   * "default"/"roomy" when a sheet wants more breathing room.
   */
  bottomGap?: BottomGapVariant;
  /** Extra classes for the sheet panel. */
  className?: string;
  /** Extra inline styles for the sheet panel (e.g. a measured maxHeight). */
  style?: ViewStyle;
}

/**
 * Bottom-sheet shell: a dimmed backdrop, a panel pinned to the bottom edge with
 * the standard rounded top, border, shadow, drag handle, and safe-area-aware
 * bottom padding. Tapping the backdrop closes; taps inside the panel don't.
 *
 * Use this instead of re-implementing the `mt-auto rounded-t-2xl …` markup so
 * every sheet shares one shape and one inset policy.
 */
export function SheetContainer({
  open,
  onClose,
  children,
  bottomGap = "compact",
  className = "",
  style,
}: SheetContainerProps) {
  const { bottom } = useScreenInsets();

  return (
    <Modal
      visible={open}
      transparent
      animationType="slide"
      onRequestClose={onClose}
      statusBarTranslucent
    >
      <Pressable className="flex-1 bg-black/40" onPress={onClose}>
        <Pressable
          onPress={() => {}}
          className={`mt-auto rounded-t-2xl border-gray-6 border-t bg-background ${className}`}
          style={{
            paddingBottom: bottom(bottomGap),
            ...SHEET_SHADOW,
            ...style,
          }}
        >
          {/* Drag handle */}
          <View className="items-center pt-2 pb-1">
            <View className="h-1 w-10 rounded-full bg-gray-6" />
          </View>
          {children}
        </Pressable>
      </Pressable>
    </Modal>
  );
}
