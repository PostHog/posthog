import { Redirect } from "expo-router";
import { useAuthStore } from "@/features/auth";

export default function Index() {
  const { isAuthenticated } = useAuthStore();

  // Redirect to tasks if authenticated, otherwise to login. The consent gate in
  // the root layout bounces unconsented users to /consent from here.
  if (isAuthenticated) {
    return <Redirect href="/(tabs)/tasks" />;
  }

  return <Redirect href="/auth" />;
}
