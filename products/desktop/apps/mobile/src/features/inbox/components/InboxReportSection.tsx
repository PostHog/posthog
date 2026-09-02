import { Text } from "@components/text";
import type { SignalReport } from "@posthog/shared/domain-types";
import { CaretDown } from "phosphor-react-native";
import { useState } from "react";
import { Pressable, View } from "react-native";
import { useThemeColors } from "@/lib/theme";

const SECTION_PREVIEW_LIMIT = 5;

interface InboxReportSectionProps {
  title: string;
  reports: SignalReport[];
  count: number;
  emptyNote?: string;
  defaultOpen?: boolean;
  renderReport: (report: SignalReport) => React.ReactNode;
  onOpenChange?: (open: boolean) => void;
}

export function InboxReportSection({
  title,
  reports,
  count,
  emptyNote,
  defaultOpen = true,
  renderReport,
  onOpenChange,
}: InboxReportSectionProps) {
  const themeColors = useThemeColors();
  const [open, setOpen] = useState(defaultOpen);
  const [visibleCount, setVisibleCount] = useState(SECTION_PREVIEW_LIMIT);
  if (count === 0 && reports.length === 0 && !emptyNote) return null;

  const visible = reports.slice(0, visibleCount);
  const remainingHidden = Math.max(0, count - visible.length);
  const revealMore = () =>
    setVisibleCount((current) =>
      Math.min(current + SECTION_PREVIEW_LIMIT, count),
    );

  return (
    <View className="mb-3">
      <Pressable
        onPress={() =>
          setOpen((current) => {
            const next = !current;
            onOpenChange?.(next);
            return next;
          })
        }
        hitSlop={6}
        accessibilityRole="button"
        accessibilityState={{ expanded: open }}
        className="mb-1 flex-row items-center gap-2 px-3 py-2 active:opacity-70"
      >
        <View className="flex-row items-center gap-1">
          <Text className="font-mono font-semibold text-[11px] text-gray-10 uppercase tracking-widest">
            {title}
          </Text>
          <Text className="font-mono text-[11px] text-gray-10 tabular-nums">
            ({count})
          </Text>
        </View>
        <View className="h-px flex-1 bg-gray-5" />
        <CaretDown
          size={12}
          color={themeColors.gray[9]}
          style={{ transform: [{ rotate: open ? "180deg" : "0deg" }] }}
        />
      </Pressable>
      {open ? (
        reports.length === 0 && emptyNote ? (
          <Text className="px-3 py-2 text-[13px] text-gray-10">
            {emptyNote}
          </Text>
        ) : (
          <View>
            {visible.map((report) => renderReport(report))}
            {remainingHidden > 0 ? (
              <Pressable
                onPress={revealMore}
                hitSlop={6}
                accessibilityRole="button"
                className="self-center px-3 py-2 active:opacity-70"
              >
                <Text className="font-medium text-[13px] text-gray-10">
                  Show more ({remainingHidden})
                </Text>
              </Pressable>
            ) : null}
          </View>
        )
      ) : null}
    </View>
  );
}
