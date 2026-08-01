import { ArrowLeft, ArrowRight } from "@phosphor-icons/react";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { Button, Callout, Flex, Spinner, Text } from "@radix-ui/themes";
import { motion } from "framer-motion";
import { happyHog } from "../../../assets/hedgehogs";
import { OnboardingHogTip } from "../../../primitives/OnboardingHogTip";
import { track } from "../../../shell/analytics";
import { useAuthUiStateStore } from "../../auth/authUiStateStore";
import { useRedeemInviteCodeMutation } from "../../auth/useAuthMutations";
import { StepActions } from "./StepActions";

interface InviteCodeStepProps {
  onNext: () => void;
  onBack: () => void;
}

export function InviteCodeStep({ onNext, onBack }: InviteCodeStepProps) {
  const code = useAuthUiStateStore((state) => state.inviteCode);
  const setInviteCode = useAuthUiStateStore((state) => state.setInviteCode);
  const resetInviteCode = useAuthUiStateStore((state) => state.resetInviteCode);
  const redeemMutation = useRedeemInviteCodeMutation();
  const errorMessage = redeemMutation.error?.message ?? null;

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!code.trim()) return;
    redeemMutation.mutate(code.trim(), {
      onSuccess: () => {
        track(ANALYTICS_EVENTS.ONBOARDING_INVITE_CODE_SUBMITTED, {
          success: true,
        });
        resetInviteCode();
        onNext();
      },
      onError: (err) => {
        track(ANALYTICS_EVENTS.ONBOARDING_INVITE_CODE_SUBMITTED, {
          success: false,
          error_type: err instanceof Error ? err.message : "unknown",
        });
      },
    });
  };

  return (
    <Flex align="center" justify="center" height="100%" px="8">
      <Flex
        direction="column"
        align="center"
        className="h-full w-full max-w-[480px] pt-[24px] pb-[40px]"
      >
        <Flex
          direction="column"
          align="center"
          className="min-h-0 w-full flex-1 overflow-y-auto"
        >
          <Flex
            direction="column"
            align="start"
            gap="5"
            style={{ margin: "auto 0" }}
            className="w-full"
          >
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
                        <>
                          Redeem
                          <ArrowRight size={16} weight="bold" />
                        </>
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

        <StepActions>
          <Button size="3" variant="outline" color="gray" onClick={onBack}>
            <ArrowLeft size={16} weight="bold" />
            Back
          </Button>
        </StepActions>
      </Flex>
    </Flex>
  );
}
