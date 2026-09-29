import { Drawer } from "expo-router/drawer";
import { DrawerContent } from "@/components/DrawerContent";
import { colors, drawer } from "@/lib/theme";

export default function DrawerLayout() {
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
        swipeEdgeWidth: 60,
      }}
    >
      <Drawer.Screen name="index" />
      <Drawer.Screen name="task/[id]" />
    </Drawer>
  );
}
