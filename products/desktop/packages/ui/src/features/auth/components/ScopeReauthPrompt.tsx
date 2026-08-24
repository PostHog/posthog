import { ShieldWarning } from "@phosphor-icons/react";
import { Button, Dialog, Flex, Text } from "@radix-ui/themes";
import { logger } from "../../../shell/logger";
import { useAuthStateValue } from "../store";
import { useLoginMutation, useLogoutMutation } from "../useAuthMutations";

const log = logger.scope("scope-reauth-prompt");

export function ScopeReauthPrompt() {
  const needsScopeReauth = useAuthStateValue((state) => state.needsScopeReauth);
  const cloudRegion = useAuthStateValue((state) => state.cloudRegion);
  const loginMutation = useLoginMutation();
  const logoutMutation = useLogoutMutation();

  const handleSignIn = async () => {
    if (!cloudRegion) {
      log.warn("Cannot re-authenticate: no cloud region available");
      return;
    }

    try {
      await loginMutation.mutateAsync(cloudRegion);
    } catch (error) {
      log.error("Re-authentication failed", error);
    }
  };

  return (
    <Dialog.Root open={needsScopeReauth}>
      <Dialog.Content
        maxWidth="360px"
        onEscapeKeyDown={(e) => e.preventDefault()}
        onInteractOutside={(e) => e.preventDefault()}
      >
        <Flex direction="column" gap="3">
          <Flex align="center" gap="2">
            <ShieldWarning size={20} weight="bold" color="var(--gray-11)" />
            <Dialog.Title className="mb-0">
              Re-authentication required
            </Dialog.Title>
          </Flex>
          <Dialog.Description>
            <Text color="gray" className="text-sm">
              PostHog has been updated with new features that require additional
              permissions. Please sign in again to continue.
            </Text>
          </Dialog.Description>
          <Flex justify="between" mt="2">
            <Button
              type="button"
              variant="soft"
              color="gray"
              onClick={() => logoutMutation.mutate()}
            >
              Log out
            </Button>
            <Button
              type="button"
              onClick={handleSignIn}
              loading={loginMutation.isPending}
              disabled={!cloudRegion}
            >
              Sign in
            </Button>
          </Flex>
        </Flex>
      </Dialog.Content>
    </Dialog.Root>
  );
}
