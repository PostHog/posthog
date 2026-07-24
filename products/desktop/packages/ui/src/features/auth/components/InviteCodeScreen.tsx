import { SignOut } from "@phosphor-icons/react";
import { happyHog } from "@posthog/ui/assets/hedgehogs";
import { FullScreenLayout } from "@posthog/ui/primitives/FullScreenLayout";
import { OnboardingHogTip } from "@posthog/ui/primitives/OnboardingHogTip";
import { Button, Callout, Flex, Spinner, Text } from "@radix-ui/themes";
import { motion } from "framer-motion";
import { useAuthUiStateStore } from "../authUiStateStore";
import {
  useLogoutMutation,
  useRedeemInviteCodeMutation,
} from "../useAuthMutations";

export function InviteCodeScreen() {
  const code = useAuthUiStateStore((state) => state.inviteCode);
  const setInviteCode = useAuthUiStateStore((state) => state.setInviteCode);
  const resetInviteCode = useAuthUiStateStore((state) => state.resetInviteCode);
  const redeemMutation = useRedeemInviteCodeMutation();
  const logoutMutation = useLogoutMutation();
  const errorMessage = redeemMutation.error?.message ?? null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!code.trim()) return;
    redeemMutation.mutate(code.trim(), {
      onSuccess: () => {
        resetInviteCode();
      },
    });
  };

  const footerRight = (
    <Button
      size="1"
      variant="ghost"
      color="gray"
      onClick={() => logoutMutation.mutate()}
      className="opacity-50"
    >
      <SignOut size={14} />
      Log out
    </Button>
  );

  return (
    <FullScreenLayout footerRight={footerRight}>
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
                <motion.div
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.3 }}
                >
                  <Flex direction="column" gap="2">
                    <Text className="font-bold text-(--gray-12) text-2xl">
                      Enter your invite code
                    </Text>
                    <Text className="text-(--gray-11) text-sm">
                      You need an invite code to access PostHog.
                    </Text>
                  </Flex>
                </motion.div>

                <motion.div
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.3, delay: 0.05 }}
                >
                  <form onSubmit={handleSubmit}>
                    <Flex direction="column" gap="3">
                      {errorMessage && (
                        <Callout.Root color="red" size="1">
                          <Callout.Text>{errorMessage}</Callout.Text>
                        </Callout.Root>
                      )}
                      <input
                        type="text"
                        value={code}
                        onChange={(e) => setInviteCode(e.target.value)}
                        placeholder="Invite code"
                        disabled={redeemMutation.isPending}
                        className="box-border h-[44px] w-full rounded-[10px] border border-(--gray-a3) bg-(--color-panel-solid) px-[14px] py-0 text-(--gray-12) text-[15px]"
                        style={{
                          outline: "none",
                          boxShadow:
                            "0 1px 3px rgba(0,0,0,0.04), 0 1px 2px rgba(0,0,0,0.02)",
                          fontFamily: "inherit",
                        }}
                      />
                      <Button
                        type="submit"
                        size="3"
                        disabled={redeemMutation.isPending || !code.trim()}
                        className="w-full"
                      >
                        {redeemMutation.isPending ? (
                          <Spinner size="1" />
                        ) : (
                          "Redeem"
                        )}
                      </Button>
                    </Flex>
                  </form>
                </motion.div>
              </Flex>

              <OnboardingHogTip
                hogSrc={happyHog}
                message="Got a code from a friend or the PostHog team? Pop it in above."
                delay={0.1}
              />
            </Flex>
          </Flex>
        </Flex>
      </Flex>
    </FullScreenLayout>
  );
}
