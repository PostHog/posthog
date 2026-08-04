import { Stack, usePathname, useRouter } from "expo-router";
import { useEffect, useRef } from "react";
import { BackHandler, PanResponder, View } from "react-native";
import { NavDrawer } from "@/features/navigation/components/NavDrawer";
import { useNavDrawerStore } from "@/features/navigation/stores/navDrawerStore";
import { useThemeColors } from "@/lib/theme";

// Edge-swipe drawer trigger: tap-and-drag from the very left edge of the
// screen pulls the drawer open. Matches iOS native back-swipe affordance
// without taking the gesture from card swipes / scroll lists deeper in.
const EDGE_SWIPE_HIT_WIDTH = 22;

const HOME_ROUTE = "/tasks";
const TAB_ROUTES = new Set(["/tasks", "/inbox", "/automations"]);

export default function TabsLayout() {
  const themeColors = useThemeColors();
  const router = useRouter();
  const pathname = usePathname();

  // Persisted across re-renders so the responder's grant doesn't get
  // rebuilt on every drawer-state change.
  const edgePanResponder = useRef(
    PanResponder.create({
      onStartShouldSetPanResponder: () => false,
      onMoveShouldSetPanResponder: (e, gesture) =>
        !useNavDrawerStore.getState().isOpen &&
        e.nativeEvent.pageX <= EDGE_SWIPE_HIT_WIDTH &&
        gesture.dx > 6 &&
        gesture.dx > Math.abs(gesture.dy),
      onMoveShouldSetPanResponderCapture: (e, gesture) =>
        !useNavDrawerStore.getState().isOpen &&
        e.nativeEvent.pageX <= EDGE_SWIPE_HIT_WIDTH &&
        gesture.dx > 10 &&
        gesture.dx > Math.abs(gesture.dy * 1.2),
      onPanResponderRelease: (_, gesture) => {
        if (gesture.dx > 40) useNavDrawerStore.getState().open();
      },
    }),
  ).current;

  // Android: each drawer destination replaces (no back stack between them), so
  // hardware back from a non-home destination should go home instead of exiting.
  useEffect(() => {
    const subscription = BackHandler.addEventListener(
      "hardwareBackPress",
      () => {
        const store = useNavDrawerStore.getState();
        // Drawer always-mounted: close it explicitly here since there's no
        // Modal onRequestClose to fall through to.
        if (store.isOpen) {
          store.close();
          return true;
        }
        // Only intercept when we're actually on a tab destination. Modals
        // pushed on top of the tabs (e.g. /automation, /task) keep this
        // handler mounted; without the guard we'd redirect to /tasks instead
        // of letting the modal dismiss naturally.
        if (!TAB_ROUTES.has(pathname)) return false;
        if (pathname === HOME_ROUTE) return false;
        router.replace(HOME_ROUTE);
        return true;
      },
    );
    return () => subscription.remove();
  }, [pathname, router]);

  return (
    <View className="flex-1 bg-background">
      <Stack
        screenOptions={{
          headerShown: false,
          contentStyle: { backgroundColor: themeColors.background },
        }}
      >
        <Stack.Screen name="tasks" />
        <Stack.Screen name="inbox" />
        <Stack.Screen name="automations" />
      </Stack>
      {/* Invisible left-edge strip that captures the open-drawer gesture. */}
      <View
        pointerEvents="box-only"
        className="absolute top-0 bottom-0 left-0 z-10"
        style={{ width: EDGE_SWIPE_HIT_WIDTH }}
        {...edgePanResponder.panHandlers}
      />
      <NavDrawer />
    </View>
  );
}
