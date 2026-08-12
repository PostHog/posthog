import { useFocusEffect, useRouter } from "expo-router";
import { useCallback, useMemo, useRef } from "react";
import { InteractionManager, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { FloatingNewTaskButton } from "@/features/tasks/components/FloatingNewTaskButton";
import { FloatingTasksHeader } from "@/features/tasks/components/FloatingTasksHeader";
import {
  TaskFilterMenu,
  useTaskFilterMenu,
} from "@/features/tasks/components/TaskFilterMenu";
import { TaskList } from "@/features/tasks/components/TaskList";
import { useTasks } from "@/features/tasks/hooks/useTasks";
import { useArchivedTasksStore } from "@/features/tasks/stores/archivedTasksStore";

export default function TasksScreen() {
  const router = useRouter();
  const insets = useSafeAreaInsets();
  const readyRef = useRef(true);
  const filterMenu = useTaskFilterMenu();
  const { tasks } = useTasks({ originProduct: "user_created" });
  const archivedTasks = useArchivedTasksStore((s) => s.archivedTasks);
  const hasActiveTasks = useMemo(
    () => tasks.some((task) => !(task.id in archivedTasks)),
    [tasks, archivedTasks],
  );

  // Block navigation while a modal dismiss animation is in progress.
  // When the screen loses focus (modal opens), readyRef is false.
  // When focus returns (modal dismissed), we wait for all native
  // animations to finish before allowing the next push.
  useFocusEffect(
    useCallback(() => {
      const handle = InteractionManager.runAfterInteractions(() => {
        readyRef.current = true;
      });
      return () => {
        readyRef.current = false;
        handle.cancel();
      };
    }, []),
  );

  const handleCreateTask = useCallback(() => {
    if (!readyRef.current) return;
    readyRef.current = false;
    router.push("/task");
  }, [router]);

  const handleTaskPress = useCallback(
    (taskId: string) => {
      if (!readyRef.current) return;
      readyRef.current = false;
      router.push(`/task/${taskId}`);
    },
    [router],
  );

  // Header occupies insets.top + 6 (top pad) + 44 (button) + 8 (bottom pad),
  // plus a small visual buffer so the first row isn't hugging the divider.
  const headerHeight = insets.top + 64;

  return (
    <View className="flex-1 bg-background">
      <TaskList
        onTaskPress={handleTaskPress}
        onCreateTask={handleCreateTask}
        contentInsetTop={headerHeight}
      />

      <FloatingTasksHeader
        onFilterPress={filterMenu.show}
        showFilter={hasActiveTasks}
      />

      {hasActiveTasks ? (
        <FloatingNewTaskButton onPress={handleCreateTask} />
      ) : null}

      <TaskFilterMenu open={filterMenu.open} onClose={filterMenu.hide} />
    </View>
  );
}
