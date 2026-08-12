import { Text } from "@components/text";
import { Check, FunnelSimple } from "phosphor-react-native";
import { useState } from "react";
import { Modal, Pressable, ScrollView, View } from "react-native";
import { useUserQuery } from "@/features/auth";
import { useScreenInsets } from "@/hooks/useScreenInsets";
import { useThemeColors } from "@/lib/theme";
import {
  type OrganizeMode,
  type SortMode,
  useTaskStore,
} from "../stores/taskStore";

interface TaskFilterMenuProps {
  open: boolean;
  onClose: () => void;
}

function SectionHeader({ title }: { title: string }) {
  return (
    <Text className="mb-1 font-semibold text-[12px] text-gray-10 uppercase tracking-wide">
      {title}
    </Text>
  );
}

interface OptionRowProps {
  label: string;
  selected: boolean;
  onPress: () => void;
}

function OptionRow({ label, selected, onPress }: OptionRowProps) {
  const themeColors = useThemeColors();
  return (
    <Pressable
      onPress={onPress}
      className="flex-row items-center justify-between rounded-md px-2 py-2.5 active:bg-gray-3"
    >
      <Text className="text-[14px] text-gray-12">{label}</Text>
      {selected && <Check size={16} color={themeColors.gray[12]} />}
    </Pressable>
  );
}

export function TaskFilterMenu({ open, onClose }: TaskFilterMenuProps) {
  const { bottom, sheetContentTop } = useScreenInsets();
  const organizeMode = useTaskStore((s) => s.organizeMode);
  const setOrganizeMode = useTaskStore((s) => s.setOrganizeMode);
  const sortMode = useTaskStore((s) => s.sortMode);
  const setSortMode = useTaskStore((s) => s.setSortMode);
  const showInternal = useTaskStore((s) => s.showInternal);
  const setShowInternal = useTaskStore((s) => s.setShowInternal);
  const { data: userData } = useUserQuery();
  const isStaff = userData?.is_staff === true;

  const pickOrganize = (mode: OrganizeMode) => {
    setOrganizeMode(mode);
  };
  const pickSort = (mode: SortMode) => {
    setSortMode(mode);
  };

  return (
    <Modal
      visible={open}
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
          <Pressable onPress={onClose}>
            <Text className="font-semibold text-[14px] text-accent-9">
              Done
            </Text>
          </Pressable>
        </View>

        <ScrollView
          contentContainerStyle={{
            paddingHorizontal: 16,
            paddingTop: 16,
            paddingBottom: bottom("roomy"),
          }}
        >
          {/* Organize */}
          <SectionHeader title="Organize" />
          <View className="mb-5">
            <OptionRow
              label="By project"
              selected={organizeMode === "by-project"}
              onPress={() => pickOrganize("by-project")}
            />
            <OptionRow
              label="Chronological list"
              selected={organizeMode === "chronological"}
              onPress={() => pickOrganize("chronological")}
            />
          </View>

          {/* Sort by */}
          <SectionHeader title="Sort by" />
          <View className="mb-5">
            <OptionRow
              label="Created"
              selected={sortMode === "created"}
              onPress={() => pickSort("created")}
            />
            <OptionRow
              label="Updated"
              selected={sortMode === "updated"}
              onPress={() => pickSort("updated")}
            />
          </View>

          {/* Task visibility (staff only) */}
          {isStaff ? (
            <>
              <SectionHeader title="Task visibility" />
              <View className="mb-5">
                <OptionRow
                  label="External"
                  selected={!showInternal}
                  onPress={() => setShowInternal(false)}
                />
                <OptionRow
                  label="Internal"
                  selected={showInternal}
                  onPress={() => setShowInternal(true)}
                />
              </View>
            </>
          ) : null}
        </ScrollView>
      </View>
    </Modal>
  );
}

interface TaskFilterButtonProps {
  onPress: () => void;
}

export function TaskFilterButton({ onPress }: TaskFilterButtonProps) {
  const themeColors = useThemeColors();
  return (
    <Pressable
      onPress={onPress}
      hitSlop={8}
      className="h-9 w-9 items-center justify-center rounded-md border border-gray-6 bg-gray-2 active:bg-gray-3"
      accessibilityLabel="Filter tasks"
      accessibilityRole="button"
    >
      <FunnelSimple size={16} color={themeColors.gray[11]} />
    </Pressable>
  );
}

export function useTaskFilterMenu() {
  const [open, setOpen] = useState(false);
  return {
    open,
    show: () => setOpen(true),
    hide: () => setOpen(false),
  };
}
