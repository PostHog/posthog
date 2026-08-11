import { useRouter } from "expo-router";
import { useCallback, useMemo, useRef, useState } from "react";
import { View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { NavDrawer } from "@/features/navigation/components/NavDrawer";
import { FloatingNewTaskButton } from "@/features/tasks/components/FloatingNewTaskButton";
import { FloatingTasksHeader } from "@/features/tasks/components/FloatingTasksHeader";
import { PinnedTasksRail } from "@/features/tasks/components/PinnedTasksRail";
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
  const { tasks } = useTasks();
  const [selectionActive, setSelectionActive] = useState(false);
  const archivedTasks = useArchivedTasksStore((s) => s.archivedTasks);
  const hasActiveTasks = useMemo(
    () => tasks.some((task) => !(task.id in archivedTasks)),
    [tasks, archivedTasks],
  );

  // Pure tap-debounce against double-pushing the same route. The previous
  // focus-effect gate (false on blur, re-armed on refocus) went permanently
  // tap-dead whenever a modal dismissal failed to deliver the focus event —
  // seen on iPad — so the gate must never depend on navigation events.
  const armAfterNavigation = useCallback(() => {
    readyRef.current = false;
    setTimeout(() => {
      readyRef.current = true;
    }, 700);
  }, []);

  const handleCreateTask = useCallback(() => {
    if (!readyRef.current) return;
    armAfterNavigation();
    router.push("/task");
  }, [router, armAfterNavigation]);

  const handleTaskPress = useCallback(
    (taskId: string) => {
      if (!readyRef.current) return;
      armAfterNavigation();
      router.push(`/task/${taskId}`);
    },
    [router, armAfterNavigation],
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
        onSelectionModeChange={setSelectionActive}
        listHeader={<PinnedTasksRail onTaskPress={handleTaskPress} />}
      />

      <FloatingTasksHeader
        onFilterPress={filterMenu.show}
        showFilter={hasActiveTasks}
      />

      {hasActiveTasks && !selectionActive ? (
        <FloatingNewTaskButton onPress={handleCreateTask} />
      ) : null}

      <TaskFilterMenu open={filterMenu.open} onClose={filterMenu.hide} />
      <NavDrawer />
    </View>
  );
}
