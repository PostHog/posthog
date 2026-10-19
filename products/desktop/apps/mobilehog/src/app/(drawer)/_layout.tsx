import { Drawer, useDrawerStatus } from "expo-router/drawer";
import { useEffect } from "react";
import { Keyboard } from "react-native";
import { DrawerContent } from "@/components/DrawerContent";
import { colors, drawer } from "@/lib/theme";

// The drawer only hides the keyboard on a swipe, and its screens stay mounted,
// so a focused composer kept the keyboard up over the drawer and the next screen.
function DismissKeyboardOnOpen(): null {
  const open = useDrawerStatus() === "open";
  useEffect(() => {
    if (open) Keyboard.dismiss();
  }, [open]);
  return null;
}

export default function DrawerLayout() {
  return (
    <Drawer
      drawerContent={(props) => (
        <>
          <DismissKeyboardOnOpen />
          <DrawerContent closeDrawer={() => props.navigation.closeDrawer()} />
        </>
      )}
      screenListeners={{ blur: () => Keyboard.dismiss() }}
      screenOptions={{
        headerShown: false,
        drawerType: "back",
        overlayColor: "transparent",
        drawerStyle: {
          width: `${drawer.widthFraction * 100}%`,
          backgroundColor: colors.bgDeep,
        },
        sceneStyle: { backgroundColor: "transparent" },
        swipeEdgeWidth: 60,
      }}
    >
      <Drawer.Screen name="index" />
      <Drawer.Screen name="task/[id]" />
      <Drawer.Screen name="activity" />
      <Drawer.Screen name="self-driving" />
      <Drawer.Screen name="recents" />
    </Drawer>
  );
}
