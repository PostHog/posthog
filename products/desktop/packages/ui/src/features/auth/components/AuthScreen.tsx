import { SignInCard } from "@posthog/ui/features/auth/SignInCard";
import { FullScreenLayout } from "@posthog/ui/primitives/FullScreenLayout";
import { Callout, Flex } from "@radix-ui/themes";
import { useAuthStateValue } from "../store";

export function AuthScreen() {
  const sessionEndReason = useAuthStateValue((state) => state.sessionEndReason);
  return (
    <FullScreenLayout>
      <Flex align="center" justify="center" height="100%" px="8">
        <Flex
          direction="column"
          align="center"
          className="h-full w-full max-w-[480px] pt-[24px] pb-[40px]"
        >
          <Flex
            direction="column"
            justify="center"
            align="center"
            className="min-h-0 w-full flex-1"
          >
            <Flex direction="column" align="start" gap="6" className="w-full">
              <Flex direction="column" gap="5" className="w-full">
                {sessionEndReason === "impersonation_expired" && (
                  <Callout.Root color="amber">
                    <Callout.Text>
                      Your impersonated session ended. Impersonate the user
                      again, then sign in to continue.
                    </Callout.Text>
                  </Callout.Root>
                )}
                <SignInCard />
              </Flex>
            </Flex>
          </Flex>
        </Flex>
      </Flex>
    </FullScreenLayout>
  );
}
