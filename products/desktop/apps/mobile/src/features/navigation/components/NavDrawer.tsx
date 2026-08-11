import { Text } from "@components/text";
import { usePathname, useRouter } from "expo-router";
import {
  Binoculars,
  BookOpen,
  Clock,
  GearSix,
  ListBullets,
  PuzzlePiece,
  Tray,
} from "phosphor-react-native";
import { memo, type ReactNode } from "react";
import { Pressable, StyleSheet, useWindowDimensions, View } from "react-native";
import { useSafeAreaInsets } from "react-native-safe-area-context";
import { OFFLINE_BANNER_HEIGHT } from "@/components/OfflineBanner";
import { useSkillsAvailable } from "@/features/tasks/skills/hooks";
import { useNetworkStatus } from "@/hooks/useNetworkStatus";
import { useThemeColors } from "@/lib/theme";
import { useNavDrawerStore } from "../stores/navDrawerStore";

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
 * Drawer body — a flat list of destinations, extracted so it doesn't re-render
 * every time the open state toggles. `paddingTop` is the only prop and only
 * changes when the offline banner appears/disappears, so the memo stays
 * effective. Deliberately owns no task data: the Tasks screen is the single
 * place tasks are listed, so opening the drawer costs no extra query.
 */
const NavDrawerContent = memo(function NavDrawerContent({
  paddingTop,
}: NavDrawerContentProps) {
  const close = useNavDrawerStore((s) => s.close);
  const router = useRouter();
  const pathname = usePathname();
  const themeColors = useThemeColors();
  const insets = useSafeAreaInsets();
  const skillsAvailable = useSkillsAvailable();

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
      {/* Mirrors the floating header's hamburger position exactly, so the
          same screen coordinates toggle the drawer whether it is open or
          closed — when open, this button on the solid panel is what you hit. */}
      <View className="flex-row items-center px-3 pb-3">
        <Pressable
          onPress={close}
          hitSlop={12}
          accessibilityLabel="Close navigation menu"
          accessibilityRole="button"
          className="h-10 w-10 items-center justify-center rounded-lg active:bg-gray-3"
        >
          <List size={24} color={themeColors.gray[12]} />
        </Pressable>
        <Pressable onPress={handleHome} className="px-2 active:opacity-60">
          <Text className="font-bold text-[20px] text-gray-12">PostHog</Text>
        </Pressable>
      </View>

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

      {/* Pushes Settings to the bottom of the panel now that nothing
          scrollable sits between the destinations and it. */}
      <View className="flex-1" />

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
  // `isOpen` is read only to gate `pointerEvents`. The drawer body is memoized
  // above so this re-render is essentially free — it just flips a prop on the
  // outer wrappers.
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
  // Matches the floating headers' row padding so the drawer's hamburger
  // lands on the same screen coordinates as the one that opened it.
  const drawerPaddingTop = isConnected ? insets.top + 6 : 6;

  // No animation at all — deliberately. Two animation systems in a row
  // (Reanimated worklets, then core Animated) have produced an invisible
  // drawer on the iPad dev build while reporting success. Static rendering
  // cannot fail that way: open renders at final position, closed renders
  // nothing. Reinstate a slide only after the static form is verified on
  // the affected device.

  if (!isOpen) return null;

  return (
    <View style={StyleSheet.absoluteFill}>
      <View
        style={[
          StyleSheet.absoluteFill,
          { backgroundColor: "rgba(0,0,0,0.4)" },
        ]}
      >
        {/* Touch-down close so the dismiss starts the moment the finger lands. */}
        <Pressable className="flex-1" onPressIn={close} />
      </View>

      <View
        className="absolute bottom-0 left-0 border-gray-6 border-r bg-gray-2"
        style={{ top: drawerTop, width: drawerWidth }}
      >
        <NavDrawerContent paddingTop={drawerPaddingTop} />
      </View>
    </View>
  );
}
