import { SignOut } from "@phosphor-icons/react";
import { formatRegionBadge } from "@posthog/shared";
import { useOptionalAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { useLogoutMutation } from "@posthog/ui/features/auth/useAuthMutations";
import { useCurrentUser } from "@posthog/ui/features/auth/useCurrentUser";
import { getUserInitials } from "@posthog/ui/features/auth/userInitials";
import { Avatar, Badge, Button, Flex, Spinner, Text } from "@radix-ui/themes";

export function AccountSettings() {
  const isAuthenticated = useAuthStateValue(
    (state) => state.status === "authenticated",
  );
  const cloudRegion = useAuthStateValue((state) => state.cloudRegion);
  const logoutMutation = useLogoutMutation();
  const client = useOptionalAuthenticatedClient();
  const { data: user, isLoading } = useCurrentUser({
    client,
    enabled: isAuthenticated,
  });

  const handleLogout = () => {
    logoutMutation.mutate();
  };

  if (!isAuthenticated) {
    return (
      <Flex direction="column" gap="3" py="4">
        <Text color="gray" className="text-sm">
          You are not currently authenticated. Please sign in from the main
          screen.
        </Text>
      </Flex>
    );
  }

  if (isLoading || !user) {
    return (
      <Flex direction="column" gap="3" py="4">
        <Spinner size="3" />
      </Flex>
    );
  }

  const initials = getUserInitials(user);

  return (
    <Flex direction="column">
      <Flex align="center" gap="4" py="4">
        <Avatar size="4" fallback={initials} radius="full" color="amber" />
        <Flex direction="column" gap="1" className="flex-1">
          <Text className="font-medium text-base">
            {user.first_name && user.last_name
              ? `${user.first_name} ${user.last_name}`
              : user.email}
          </Text>
          <Flex align="center" gap="2">
            <Text color="gray" className="text-sm">
              {user.email}
            </Text>
            {cloudRegion && (
              <Badge size="1" variant="soft">
                {formatRegionBadge(cloudRegion)}
              </Badge>
            )}
          </Flex>
        </Flex>
        <Button
          variant="outline"
          color="red"
          size="1"
          onClick={handleLogout}
          className="cursor-pointer"
        >
          <SignOut size={14} />
          Sign out
        </Button>
      </Flex>
    </Flex>
  );
}
