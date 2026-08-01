import { happyHog } from "@posthog/ui/assets/hedgehogs";
import { FullScreenLayout } from "@posthog/ui/primitives/FullScreenLayout";
import { Callout, Flex } from "@radix-ui/themes";
import { useAuthStateValue } from "../store";
import { SignInCard } from "./SignInCard";

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
                <SignInCard
                  hogSrc={happyHog}
                  hogMessage="Welcome back. Let's get shipping."
                  subtitle="Connect your PostHog account to continue."
                />
              </Flex>
            </Flex>
          </Flex>
        </Flex>
      </Flex>
    </FullScreenLayout>
  );
}
