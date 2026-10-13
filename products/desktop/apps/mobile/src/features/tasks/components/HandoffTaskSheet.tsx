import { Text } from "@components/text";
import { getUserInitials } from "@posthog/core/auth/userInitials";
import type { Task } from "@posthog/shared";
import type { UserBasic } from "@posthog/shared/domain-types";
import * as Haptics from "expo-haptics";
import { Check, MagnifyingGlass } from "phosphor-react-native";
import { useMemo, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  FlatList,
  Modal,
  Pressable,
  TextInput,
  View,
} from "react-native";
import { useUserQuery } from "@/features/auth";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { useScreenInsets } from "@/hooks/useScreenInsets";
import { useThemeColors } from "@/lib/theme";
import { useOrgMembers } from "../hooks/useOrgMembers";
import { useHandoffTask } from "../hooks/useTasks";
import { userDisplayName } from "../utils/userDisplayName";

interface HandoffTaskSheetProps {
  visible: boolean;
  task: Task;
  onClose: () => void;
  // The detail screen holds its own task/session state that a handoff makes
  // stale (and may revoke access to), so the host leaves the screen on success.
  onHandedOff: () => void;
}

function MemberRow({
  member,
  selected,
  onPress,
}: {
  member: UserBasic;
  selected: boolean;
  onPress: () => void;
}) {
  const themeColors = useThemeColors();
  return (
    <Pressable
      onPress={onPress}
      className="flex-row items-center justify-between rounded-md px-2 py-2.5 active:bg-gray-3"
    >
      <View className="min-w-0 flex-1 flex-row items-center gap-2.5">
        <View className="h-6 w-6 items-center justify-center rounded-full bg-gray-4">
          <Text className="text-[11px] text-gray-10">
            {getUserInitials(member)}
          </Text>
        </View>
        <View className="min-w-0 flex-1">
          <Text className="text-[14px] text-gray-12" numberOfLines={1}>
            {userDisplayName(member)}
          </Text>
          <Text className="text-[12px] text-gray-9" numberOfLines={1}>
            {member.email}
          </Text>
        </View>
      </View>
      {selected && <Check size={16} color={themeColors.gray[12]} />}
    </Pressable>
  );
}

export function HandoffTaskSheet({
  visible,
  task,
  onClose,
  onHandedOff,
}: HandoffTaskSheetProps) {
  const { bottom, sheetContentTop } = useScreenInsets();
  const themeColors = useThemeColors();
  const { data: currentUser } = useUserQuery();
  const { mutate: handoffTask, isPending } = useHandoffTask();
  const { members, isLoading } = useOrgMembers({ enabled: visible });

  const [query, setQuery] = useState("");
  const debouncedQuery = useDebouncedValue(query, 250);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [acknowledged, setAcknowledged] = useState(false);

  const [wasVisible, setWasVisible] = useState(visible);
  if (visible !== wasVisible) {
    setWasVisible(visible);
    if (visible) {
      setQuery("");
      setSelectedId(null);
      setAcknowledged(false);
    }
  }

  const options = useMemo(() => {
    const needle = debouncedQuery.trim().toLowerCase();
    return members.filter((member) => {
      if (member.id === currentUser?.id) return false;
      if (!needle) return true;
      return (
        userDisplayName(member).toLowerCase().includes(needle) ||
        member.email.toLowerCase().includes(needle)
      );
    });
  }, [members, currentUser?.id, debouncedQuery]);

  const selected = options.find((member) => member.id === selectedId);
  const canSubmit = selected !== undefined && acknowledged && !isPending;

  const handleConfirm = () => {
    if (!selected) return;
    Haptics.impactAsync(Haptics.ImpactFeedbackStyle.Medium);
    handoffTask(
      { taskId: task.id, userId: selected.id },
      {
        onSuccess: onHandedOff,
        onError: () => {
          Alert.alert(
            "Couldn't hand off",
            "The task could not be handed off. Please try again.",
          );
        },
      },
    );
  };

  return (
    <Modal
      visible={visible}
      animationType="slide"
      presentationStyle="pageSheet"
      onRequestClose={isPending ? undefined : onClose}
    >
      <View
        className="flex-1 bg-background"
        style={{ paddingTop: sheetContentTop() }}
      >
        <View className="flex-row items-center justify-between border-gray-6 border-b px-4 pb-3">
          <Text className="font-semibold text-[18px] text-gray-12">
            Hand off task
          </Text>
          <Pressable onPress={onClose} disabled={isPending}>
            <Text className="font-semibold text-[14px] text-accent-9">
              Cancel
            </Text>
          </Pressable>
        </View>

        <View className="gap-1 px-4 pt-3">
          <Text className="text-[13px] text-gray-11">
            <Text className="font-medium text-gray-12">{task.title}</Text> goes
            to the person you pick. They steer it and get its notifications.
          </Text>
          <Text className="text-[13px] text-gray-11">
            If it's in your personal space, it moves to theirs and you lose
            access. Only they can hand it back.
          </Text>
        </View>

        <View className="px-4 pt-3">
          <View className="flex-row items-center gap-2 rounded-lg bg-gray-2 px-3 py-2">
            <MagnifyingGlass size={16} color={themeColors.gray[9]} />
            <TextInput
              value={query}
              onChangeText={setQuery}
              placeholder="Search people…"
              placeholderTextColor={themeColors.gray[9]}
              autoCapitalize="none"
              autoCorrect={false}
              className="min-w-0 flex-1 text-[14px] text-gray-12"
            />
          </View>
        </View>

        {options.length === 0 ? (
          isLoading ? (
            <View className="flex-1 items-center justify-center">
              <ActivityIndicator size="large" color={themeColors.accent[9]} />
            </View>
          ) : (
            <View className="flex-1 items-center justify-center p-6">
              <Text className="text-[14px] text-gray-10">No people found</Text>
            </View>
          )
        ) : (
          <FlatList
            className="flex-1"
            data={options}
            keyExtractor={(member) => String(member.id)}
            keyboardShouldPersistTaps="handled"
            contentContainerStyle={{ paddingHorizontal: 16, paddingTop: 12 }}
            renderItem={({ item }) => (
              <MemberRow
                member={item}
                selected={item.id === selectedId}
                onPress={() => setSelectedId(item.id)}
              />
            )}
          />
        )}

        <View
          className="gap-3 border-gray-6 border-t px-4 pt-3"
          style={{ paddingBottom: bottom("roomy") }}
        >
          <Pressable
            onPress={() => setAcknowledged((prev) => !prev)}
            disabled={isPending}
            className="flex-row items-center gap-2.5 active:opacity-70"
          >
            <View
              className={`h-5 w-5 items-center justify-center rounded border ${acknowledged ? "border-transparent" : "border-gray-7"}`}
              style={
                acknowledged ? { backgroundColor: themeColors.accent[9] } : null
              }
            >
              {acknowledged ? (
                <Check size={12} color="#fff" weight="bold" />
              ) : null}
            </View>
            <Text className="flex-1 text-[13px] text-gray-11">
              I understand I can't undo this myself.
            </Text>
          </Pressable>

          <Pressable
            onPress={handleConfirm}
            disabled={!canSubmit}
            className="h-11 flex-row items-center justify-center rounded-lg active:opacity-80"
            style={{
              backgroundColor: canSubmit
                ? themeColors.accent[9]
                : themeColors.gray[4],
            }}
          >
            {isPending ? (
              <ActivityIndicator color="#fff" />
            ) : (
              <Text
                className="font-semibold text-[15px]"
                style={{ color: canSubmit ? "#fff" : themeColors.gray[9] }}
              >
                Hand off
              </Text>
            )}
          </Pressable>
        </View>
      </View>
    </Modal>
  );
}
