import { usePathname } from "expo-router";
import { Drawer } from "expo-router/drawer";
import { useEffect } from "react";
import { DrawerContent } from "@/components/DrawerContent";
import { useNavHistory } from "@/lib/history";
import { colors, drawer } from "@/lib/theme";

export default function DrawerLayout() {
  const pathname = usePathname();
  const record = useNavHistory((s) => s.record);
  useEffect(() => record(pathname), [pathname, record]);
  return (
    <Drawer
      drawerContent={(props) => (
        <DrawerContent closeDrawer={() => props.navigation.closeDrawer()} />
      )}
      screenOptions={{
        headerShown: false,
        drawerType: "back",
        overlayColor: "transparent",
        drawerStyle: {
          width: `${drawer.widthFraction * 100}%`,
          backgroundColor: colors.bgDeep,
        },
        sceneStyle: { backgroundColor: "transparent" },
        swipeEdgeWidth: drawer.swipeEdgeWidth,
      }}
    >
      <Drawer.Screen name="index" />
      <Drawer.Screen name="task/[id]" />
      <Drawer.Screen name="activity" />
      <Drawer.Screen name="self-driving" />
    </Drawer>
  );
}
