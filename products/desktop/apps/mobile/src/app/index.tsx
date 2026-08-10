import { Redirect } from "expo-router";
import { useAuthStore } from "@/features/auth";

export default function Index() {
  const { isAuthenticated } = useAuthStore();

  // Redirect to tasks if authenticated, otherwise to login
  if (isAuthenticated) {
    return <Redirect href="/(tabs)/tasks" />;
  }

  return <Redirect href="/auth" />;
}
