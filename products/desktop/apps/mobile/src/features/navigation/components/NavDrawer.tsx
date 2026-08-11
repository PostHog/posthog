import { Text } from "@components/text";
import { usePathname, useRouter } from "expo-router";
import {
  Binoculars,
  BookOpen,
  CaretRight,
  Clock,
  GearSix,
  ListBullets,
  PuzzlePiece,
  Tray,
} from "phosphor-react-native";
import {
  memo,
  type ReactNode,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  Animated,
  Easing,
  Pressable,
  ScrollView,
  StyleSheet,
  useWindowDimensions,
  View,
} from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { OFFLINE_BANNER_HEIGHT } from "@/components/OfflineBanner";
import { TaskStatusIcon } from "@/features/tasks/components/TaskStatusIcon";
import { useTasks } from "@/features/tasks/hooks/useTasks";
import { useSkillsAvailable } from "@/features/tasks/skills/hooks";
import { useArchivedTasksStore } from "@/features/tasks/stores/archivedTasksStore";
import { useNetworkStatus } from "@/hooks/useNetworkStatus";
import { logger } from "@/lib/logger";
import { useThemeColors } from "@/lib/theme";
import { useNavDrawerStore } from "../stores/navDrawerStore";
import { SwipeableArchivedDrawerRow } from "./SwipeableArchivedDrawerRow";

const log = logger.scope("nav-drawer-view");

const OPEN_DURATION = 280;
const CLOSE_DURATION = 220;

interface DrawerItemProps {
  icon: ReactNode;
  label: string;
  active?: boolean;
  onPress: () => void;
}

function DrawerItem({ icon, label, active, onPress }: DrawerItemProps) {
  return (
    <Pressable
      onPress={onPress}
      className={`flex-row items-center gap-3 rounded-md px-3 py-3 ${active ? "bg-gray-3" : "active:bg-gray-2"}`}
    >
      <View className="h-6 w-6 shrink-0 items-center justify-center">
        {icon}
      </View>
      <Text
        className="flex-1 font-medium text-[16px] text-gray-12"
        numberOfLines={1}
      >
        {label}
      </Text>
    </Pressable>
  );
}

interface NavDrawerContentProps {
  paddingTop: number;
}

/**
 * Heavy drawer body — extracted so it doesn't re-render every time the open
 * state toggles. `paddingTop` is the only prop and only changes when the
 * offline banner appears/disappears, so the memo stays effective.
 */
const NavDrawerContent = memo(function NavDrawerContent({
  paddingTop,
}: NavDrawerContentProps) {
  const close = useNavDrawerStore((s) => s.close);
  const router = useRouter();
  const pathname = usePathname();
  const themeColors = useThemeColors();
  const insets = useSafeAreaInsets();
  const { tasks } = useTasks();
  const skillsAvailable = useSkillsAvailable();
  const { archivedTasks, unarchive } = useArchivedTasksStore();
  const [archivedExpanded, setArchivedExpanded] = useState(false);

  const { activeTasks, archivedTaskList } = useMemo(() => {
    const active: typeof tasks = [];
    const archived: typeof tasks = [];
    for (const task of tasks) {
      if (task.id in archivedTasks) {
        archived.push(task);
      } else {
        active.push(task);
      }
    }
    archived.sort(
      (a, b) => (archivedTasks[b.id] ?? 0) - (archivedTasks[a.id] ?? 0),
    );
    return { activeTasks: active, archivedTaskList: archived };
  }, [tasks, archivedTasks]);

  const navigateTo = (target: string) => {
    close();
    if (pathname === target) return;
    router.replace(target);
  };

  const handleTasks = () => navigateTo("/tasks");
  const handleInbox = () => navigateTo("/inbox");
  const handleAutomations = () => navigateTo("/automations");
  // Settings is pushed (not replaced) so back / swipe-back returns the user
  // to whichever tab they were viewing when they opened the drawer.
  const handleSettings = () => {
    close();
    if (pathname === "/settings") return;
    router.push("/settings");
  };
  const handleScouts = () => {
    close();
    if (pathname === "/scouts") return;
    router.push("/scouts");
  };
  const handleSkills = () => {
    close();
    if (pathname === "/skills") return;
    router.push("/skills");
  };
  const handleMcpServers = () => {
    close();
    if (pathname === "/mcp-servers") return;
    router.push("/mcp-servers");
  };
  const handleHome = () => navigateTo("/tasks");

  const handleTaskPress = (taskId: string) => {
    close();
    router.push(`/task/${taskId}`);
  };

  const iconColor = themeColors.gray[11];
  const iconColorActive = themeColors.gray[12];
  const isOnTasks = pathname === "/tasks";
  const isOnInbox = pathname === "/inbox";
  const isOnAutomations = pathname === "/automations";
  const isOnSettings = pathname === "/settings";
  const isOnScouts = pathname === "/scouts";
  const isOnSkills = pathname.startsWith("/skills");
  const isOnMcpServers = pathname === "/mcp-servers";

  return (
    <View
      className="flex-1"
      style={{ paddingTop, paddingBottom: insets.bottom }}
    >
      <Pressable onPress={handleHome} className="px-4 pb-3 active:opacity-60">
        <Text className="font-bold text-[20px] text-gray-12">PostHog</Text>
      </Pressable>

      <View className="gap-0.5 px-2 pb-2">
        <DrawerItem
          icon={
            <ListBullets
              size={22}
              color={isOnTasks ? iconColorActive : iconColor}
              weight={isOnTasks ? "bold" : "regular"}
            />
          }
          label="Tasks"
          active={isOnTasks}
          onPress={handleTasks}
        />
        <DrawerItem
          icon={
            <Tray
              size={22}
              color={isOnInbox ? iconColorActive : iconColor}
              weight={isOnInbox ? "fill" : "regular"}
            />
          }
          label="Inbox"
          active={isOnInbox}
          onPress={handleInbox}
        />
        <DrawerItem
          icon={
            <Clock
              size={22}
              color={isOnAutomations ? iconColorActive : iconColor}
              weight={isOnAutomations ? "fill" : "regular"}
            />
          }
          label="Automations"
          active={isOnAutomations}
          onPress={handleAutomations}
        />
        <DrawerItem
          icon={
            <Binoculars
              size={22}
              color={isOnScouts ? iconColorActive : iconColor}
              weight={isOnScouts ? "fill" : "regular"}
            />
          }
          label="Scouts"
          active={isOnScouts}
          onPress={handleScouts}
        />
        {/* Hidden until the skills API confirms this project can use it — a
            403 there is how a project without the feature reads, and an entry
            that dead-ends is worse than no entry. */}
        {skillsAvailable ? (
          <DrawerItem
            icon={
              <BookOpen
                size={22}
                color={isOnSkills ? iconColorActive : iconColor}
                weight={isOnSkills ? "fill" : "regular"}
              />
            }
            label="Skills"
            active={isOnSkills}
            onPress={handleSkills}
          />
        ) : null}
        <DrawerItem
          icon={
            <PuzzlePiece
              size={22}
              color={isOnMcpServers ? iconColorActive : iconColor}
              weight={isOnMcpServers ? "fill" : "regular"}
            />
          }
          label="MCP servers"
          active={isOnMcpServers}
          onPress={handleMcpServers}
        />
      </View>

      <View className="mx-3 mb-1 border-gray-6 border-t" />

      <View className="px-4 pt-3 pb-1.5">
        <Text
          className="font-medium text-[11px] text-gray-10 uppercase"
          style={{ letterSpacing: 0.5 }}
        >
          Tasks
        </Text>
      </View>

      <ScrollView
        className="flex-1"
        contentContainerStyle={{ paddingHorizontal: 8, paddingBottom: 12 }}
      >
        {activeTasks.length === 0 && archivedTaskList.length === 0 ? (
          <View className="px-2.5 py-2">
            <Text className="text-[13px] text-gray-10">No tasks yet</Text>
          </View>
        ) : (
          <>
            {activeTasks.map((task) => {
              const taskHref = `/task/${task.id}`;
              const active = pathname === taskHref;
              return (
                <Pressable
                  key={task.id}
                  onPress={() => handleTaskPress(task.id)}
                  className={`flex-row items-center gap-3 rounded-md px-3 py-2.5 ${active ? "bg-gray-3" : "active:bg-gray-2"}`}
                >
                  <View className="h-5 w-5 shrink-0 items-center justify-center">
                    <TaskStatusIcon task={task} size={16} />
                  </View>
                  <Text
                    className="flex-1 text-[15px] text-gray-12"
                    numberOfLines={1}
                    ellipsizeMode="tail"
                  >
                    {task.title}
                  </Text>
                </Pressable>
              );
            })}

            {archivedTaskList.length > 0 && (
              <View className="mt-2">
                <Pressable
                  onPress={() => setArchivedExpanded((prev) => !prev)}
                  className="flex-row items-center gap-2 rounded-md px-3 py-2 active:bg-gray-2"
                >
                  <CaretRight
                    size={12}
                    color={themeColors.gray[10]}
                    style={{
                      transform: [
                        { rotate: archivedExpanded ? "90deg" : "0deg" },
                      ],
                    }}
                  />
                  <Text
                    className="flex-1 font-medium text-[11px] text-gray-10 uppercase"
                    style={{ letterSpacing: 0.5 }}
                  >
                    Archived
                  </Text>
                  <Text className="text-[11px] text-gray-9">
                    {archivedTaskList.length}
                  </Text>
                </Pressable>

                {archivedExpanded &&
                  archivedTaskList.map((task) => {
                    const taskHref = `/task/${task.id}`;
                    return (
                      <SwipeableArchivedDrawerRow
                        key={task.id}
                        task={task}
                        active={pathname === taskHref}
                        onPress={handleTaskPress}
                        onUnarchive={unarchive}
                      />
                    );
                  })}
              </View>
            )}
          </>
        )}
      </ScrollView>

      <View className="mx-3 mt-1 border-gray-6 border-t" />

      <View className="gap-0.5 px-2 pt-2 pb-2">
        <DrawerItem
          icon={
            <GearSix
              size={22}
              color={isOnSettings ? iconColorActive : iconColor}
              weight={isOnSettings ? "fill" : "regular"}
            />
          }
          label="Settings"
          active={isOnSettings}
          onPress={handleSettings}
        />
      </View>
    </View>
  );
});

export function NavDrawer() {
  // `isOpen` is read only to gate `pointerEvents`. The heavy drawer body is
  // memoized below so this re-render is essentially free — it just flips a
  // prop on the outer wrappers.
  const isOpen = useNavDrawerStore((s) => s.isOpen);
  const close = useNavDrawerStore((s) => s.close);
  const insets = useSafeAreaInsets();
  const { isConnected } = useNetworkStatus();
  // Live window width (not a module-scope capture): stays correct through
  // rotation, Split View, and Stage Manager, and can never be 0 from a
  // prewarmed launch before a window exists.
  const { width: windowWidth } = useWindowDimensions();
  const drawerWidth = Math.min(320, Math.round(windowWidth * 0.85));

  // When offline, the banner occupies `insets.top + OFFLINE_BANNER_HEIGHT` at
  // the top of the screen — push the panel down by that amount and drop the
  // inner safe-area padding to compensate.
  const drawerTop = isConnected ? 0 : insets.top + OFFLINE_BANNER_HEIGHT;
  const drawerPaddingTop = isConnected ? insets.top + 12 : 12;

  // Core RN Animated (JS-driven), deliberately not Reanimated: on some dev
  // builds the worklets runtime silently fails to initialize, and every
  // Reanimated style no-ops — which left this drawer permanently translated
  // off-screen while its state said "open". The JS driver has no such
  // dependency and animating opacity/transform stays on the native driver.
  const progress = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    progress.setValue(useNavDrawerStore.getState().isOpen ? 1 : 0);
    return useNavDrawerStore.subscribe((state, prev) => {
      if (state.isOpen === prev.isOpen) return;
      log.debug("drawer state change", { isOpen: state.isOpen });
      Animated.timing(progress, {
        toValue: state.isOpen ? 1 : 0,
        duration: state.isOpen ? OPEN_DURATION : CLOSE_DURATION,
        easing: state.isOpen
          ? Easing.out(Easing.cubic)
          : Easing.in(Easing.cubic),
        useNativeDriver: true,
      }).start();
    });
  }, [progress]);

  const drawerStyle = {
    transform: [
      {
        translateX: progress.interpolate({
          inputRange: [0, 1],
          outputRange: [-drawerWidth, 0],
        }),
      },
    ],
  };

  const backdropStyle = { opacity: progress };

  return (
    <View
      pointerEvents={isOpen ? "auto" : "none"}
      style={StyleSheet.absoluteFillObject}
    >
      <Animated.View
        pointerEvents={isOpen ? "auto" : "none"}
        style={[
          StyleSheet.absoluteFillObject,
          { backgroundColor: "rgba(0,0,0,0.4)" },
          backdropStyle,
        ]}
      >
        {/* Touch-down close so the dismiss starts the moment the finger lands. */}
        <Pressable className="flex-1" onPressIn={close} />
      </Animated.View>

      <Animated.View
        className="absolute bottom-0 left-0 border-gray-6 border-r bg-gray-2"
        style={[{ top: drawerTop, width: drawerWidth }, drawerStyle]}
      >
        <NavDrawerContent paddingTop={drawerPaddingTop} />
      </Animated.View>
    </View>
  );
}
