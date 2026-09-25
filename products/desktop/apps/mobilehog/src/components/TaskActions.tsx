import type { Task } from "@posthog/shared/domain-types";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { useState } from "react";
import {
  Alert,
  Modal,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { GlassCircleButton } from "@/components/Glass";
import { OptionsSheet } from "@/components/OptionsSheet";
import { getClient } from "@/lib/client";
import { colors, fonts } from "@/lib/theme";

export function TaskActions({
  task,
  archived = false,
}: {
  task: Task;
  archived?: boolean;
}) {
  const router = useRouter();
  const client = useQueryClient();
  const [menu, setMenu] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [title, setTitle] = useState(task.title);
  const mutation = useMutation({
    mutationFn: (patch: { title?: string; archived?: boolean }) =>
      getClient().updateTask(task.id, patch),
    onSuccess: (_task, patch) => {
      void client.invalidateQueries({ queryKey: ["tasks"] });
      setRenaming(false);
      if (patch.archived !== undefined) router.replace("/(drawer)");
    },
    onError: () =>
      Alert.alert(
        "Could not update task",
        "Check your connection and try again.",
      ),
  });
  return (
    <>
      <GlassCircleButton
        accessibilityLabel="Task options"
        disabled={mutation.isPending}
        onPress={() => setMenu(true)}
      >
        <Text style={styles.more}>⋯</Text>
      </GlassCircleButton>
      {menu ? (
        <OptionsSheet
          title="Task options"
          onClose={() => setMenu(false)}
          options={[
            {
              label: "Rename",
              onPress: () => {
                setTitle(task.title);
                setRenaming(true);
              },
            },
            {
              label: archived ? "Restore task" : "Archive task",
              onPress: () =>
                Alert.alert(
                  archived ? "Restore task?" : "Archive task?",
                  archived
                    ? "This task will return to the task list."
                    : "This hides the task on mobile and Desktop. It does not stop a running task.",
                  [
                    { text: "Cancel", style: "cancel" },
                    {
                      text: archived ? "Restore" : "Archive",
                      onPress: () => mutation.mutate({ archived: !archived }),
                    },
                  ],
                ),
            },
          ]}
        />
      ) : null}
      <Modal
        visible={renaming}
        transparent
        animationType="fade"
        onRequestClose={() => setRenaming(false)}
      >
        <View style={styles.overlay}>
          <View style={styles.card} accessibilityViewIsModal>
            <Text style={styles.heading}>Rename task</Text>
            <TextInput
              accessibilityLabel="Task title"
              value={title}
              onChangeText={setTitle}
              maxLength={255}
              autoFocus
              multiline
              style={styles.input}
              editable={!mutation.isPending}
            />
            <View style={styles.actions}>
              <Pressable
                accessibilityRole="button"
                disabled={mutation.isPending}
                onPress={() => setRenaming(false)}
                style={styles.button}
              >
                <Text style={styles.label}>Cancel</Text>
              </Pressable>
              <Pressable
                accessibilityRole="button"
                disabled={mutation.isPending || !title.trim()}
                onPress={() => mutation.mutate({ title: title.trim() })}
                style={styles.button}
              >
                <Text style={styles.label}>
                  {mutation.isPending ? "Saving" : "Save"}
                </Text>
              </Pressable>
            </View>
          </View>
        </View>
      </Modal>
    </>
  );
}
const styles = StyleSheet.create({
  more: { color: colors.ink, fontSize: 24 },
  overlay: {
    flex: 1,
    justifyContent: "center",
    padding: 24,
    backgroundColor: "rgba(0,0,0,0.4)",
  },
  card: {
    padding: 20,
    borderRadius: 20,
    backgroundColor: colors.surface,
    gap: 16,
  },
  heading: { fontSize: 20, fontFamily: fonts.sansSemi, color: colors.ink },
  input: {
    minHeight: 60,
    fontSize: 17,
    color: colors.ink,
    fontFamily: fonts.sans,
  },
  actions: { flexDirection: "row", justifyContent: "flex-end", gap: 12 },
  button: { minHeight: 44, justifyContent: "center", paddingHorizontal: 12 },
  label: { color: colors.accent, fontSize: 16, fontFamily: fonts.sansMedium },
});
