import { Text } from "@components/text";
import { EXTERNAL_INBOX_SOURCES } from "@posthog/shared";
import { Check } from "phosphor-react-native";
import { Modal, Pressable, ScrollView, View } from "react-native";
import { useScreenInsets } from "@/hooks/useScreenInsets";
import { useThemeColors } from "@/lib/theme";
import {
  type SourceProduct,
  useInboxFilterStore,
} from "../stores/inboxFilterStore";
import type { SignalReportPriority, SignalReportStatus } from "../types";
import { inboxStatusLabel } from "../utils";

interface FilterSheetProps {
  visible: boolean;
  onClose: () => void;
}

type SortOption = {
  label: string;
  field: "priority" | "created_at" | "total_weight";
  direction: "asc" | "desc";
};

const SORT_OPTIONS: SortOption[] = [
  { label: "Priority", field: "priority", direction: "asc" },
  { label: "Strongest signal", field: "total_weight", direction: "desc" },
  { label: "Newest first", field: "created_at", direction: "desc" },
  { label: "Oldest first", field: "created_at", direction: "asc" },
];

const FILTERABLE_STATUSES: SignalReportStatus[] = [
  "ready",
  "pending_input",
  "in_progress",
  "failed",
  "candidate",
  "potential",
];

function useStatusDotColors(): Record<string, string> {
  const themeColors = useThemeColors();
  return {
    ready: themeColors.status.success,
    pending_input: themeColors.accent[9],
    in_progress: themeColors.status.warning,
    candidate: themeColors.status.info,
    potential: themeColors.gray[9],
    failed: themeColors.status.error,
  };
}

const FILTERABLE_PRIORITIES: SignalReportPriority[] = [
  "P0",
  "P1",
  "P2",
  "P3",
  "P4",
];

function usePriorityDotColors(): Record<SignalReportPriority, string> {
  const themeColors = useThemeColors();
  return {
    P0: themeColors.status.error,
    P1: themeColors.status.warning,
    P2: themeColors.status.warning,
    P3: themeColors.gray[9],
    P4: themeColors.gray[9],
  };
}

export const SOURCE_PRODUCT_OPTIONS: { value: SourceProduct; label: string }[] =
  [
    { value: "session_replay", label: "Session replay" },
    { value: "error_tracking", label: "Error tracking" },
    { value: "llm_analytics", label: "AI observability" },
    { value: "conversations", label: "Conversations" },
    { value: "signals_scout", label: "Scout" },
    { value: "health_checks", label: "Health checks" },
    ...EXTERNAL_INBOX_SOURCES.map((source) => ({
      value: source.product,
      label: source.label,
    })),
  ];

function SectionHeader({ title }: { title: string }) {
  return (
    <Text className="mb-1 font-semibold text-[12px] text-gray-10 uppercase tracking-wide">
      {title}
    </Text>
  );
}

function OptionRow({
  label,
  selected,
  onPress,
  left,
}: {
  label: string;
  selected: boolean;
  onPress: () => void;
  left?: React.ReactNode;
}) {
  const themeColors = useThemeColors();
  return (
    <Pressable
      onPress={onPress}
      className="flex-row items-center justify-between rounded-md px-2 py-2.5 active:bg-gray-3"
    >
      <View className="flex-row items-center gap-2">
        {left}
        <Text className="text-[14px] text-gray-12">{label}</Text>
      </View>
      {selected && <Check size={16} color={themeColors.gray[12]} />}
    </Pressable>
  );
}

export function FilterSheet({ visible, onClose }: FilterSheetProps) {
  const { bottom, sheetContentTop } = useScreenInsets();
  const themeColors = useThemeColors();
  const statusDotColors = useStatusDotColors();
  const priorityDotColors = usePriorityDotColors();

  const sortField = useInboxFilterStore((s) => s.sortField);
  const sortDirection = useInboxFilterStore((s) => s.sortDirection);
  const setSort = useInboxFilterStore((s) => s.setSort);
  const statusFilter = useInboxFilterStore((s) => s.statusFilter);
  const toggleStatus = useInboxFilterStore((s) => s.toggleStatus);
  const sourceProductFilter = useInboxFilterStore((s) => s.sourceProductFilter);
  const toggleSourceProduct = useInboxFilterStore((s) => s.toggleSourceProduct);
  const clearSourceProductFilter = useInboxFilterStore(
    (s) => s.clearSourceProductFilter,
  );
  const priorityFilter = useInboxFilterStore((s) => s.priorityFilter);
  const togglePriority = useInboxFilterStore((s) => s.togglePriority);
  const setPriorityFilter = useInboxFilterStore((s) => s.setPriorityFilter);
  const resetFilters = useInboxFilterStore((s) => s.resetFilters);

  const hasActiveFilters =
    sourceProductFilter.length > 0 ||
    priorityFilter.length > 0 ||
    statusFilter.length < FILTERABLE_STATUSES.length;

  return (
    <Modal
      visible={visible}
      animationType="slide"
      presentationStyle="pageSheet"
      onRequestClose={onClose}
    >
      <View
        className="flex-1 bg-background"
        style={{ paddingTop: sheetContentTop() }}
      >
        {/* Header */}
        <View className="flex-row items-center justify-between border-gray-6 border-b px-4 pb-3">
          <Text className="font-semibold text-[18px] text-gray-12">
            Filter & Sort
          </Text>
          <View className="flex-row items-center gap-3">
            {hasActiveFilters && (
              <Pressable onPress={resetFilters}>
                <Text className="text-[14px] text-accent-9">Reset</Text>
              </Pressable>
            )}
            <Pressable onPress={onClose}>
              <Text className="font-semibold text-[14px] text-accent-9">
                Done
              </Text>
            </Pressable>
          </View>
        </View>

        <ScrollView
          contentContainerStyle={{
            paddingHorizontal: 16,
            paddingTop: 16,
            paddingBottom: bottom("roomy"),
          }}
        >
          {/* Sort */}
          <SectionHeader title="Sort by" />
          <View className="mb-5">
            {SORT_OPTIONS.map((option) => (
              <OptionRow
                key={`${option.field}-${option.direction}`}
                label={option.label}
                selected={
                  sortField === option.field &&
                  sortDirection === option.direction
                }
                onPress={() => setSort(option.field, option.direction)}
              />
            ))}
          </View>

          {/* Status */}
          <SectionHeader title="Status" />
          <View className="mb-5">
            {FILTERABLE_STATUSES.map((status) => (
              <OptionRow
                key={status}
                label={inboxStatusLabel(status)}
                selected={statusFilter.includes(status)}
                onPress={() => toggleStatus(status)}
                left={
                  <View
                    className="h-2.5 w-2.5 rounded-full"
                    style={{
                      backgroundColor:
                        statusDotColors[status] ?? themeColors.gray[8],
                    }}
                  />
                }
              />
            ))}
          </View>

          {/* Priority */}
          <SectionHeader title="Priority" />
          <View className="mb-5">
            <OptionRow
              label="Any"
              selected={priorityFilter.length === 0}
              onPress={() => setPriorityFilter([])}
            />
            {FILTERABLE_PRIORITIES.map((priority) => (
              <OptionRow
                key={priority}
                label={priority}
                selected={priorityFilter.includes(priority)}
                onPress={() => togglePriority(priority)}
                left={
                  <View
                    className="h-2.5 w-2.5 rounded-full"
                    style={{ backgroundColor: priorityDotColors[priority] }}
                  />
                }
              />
            ))}
          </View>

          {/* Source */}
          <SectionHeader title="Source" />
          <View className="mb-5">
            <OptionRow
              label="Any"
              selected={sourceProductFilter.length === 0}
              onPress={clearSourceProductFilter}
            />
            {SOURCE_PRODUCT_OPTIONS.map((option) => (
              <OptionRow
                key={option.value}
                label={option.label}
                selected={sourceProductFilter.includes(option.value)}
                onPress={() => toggleSourceProduct(option.value)}
              />
            ))}
          </View>
        </ScrollView>
      </View>
    </Modal>
  );
}
