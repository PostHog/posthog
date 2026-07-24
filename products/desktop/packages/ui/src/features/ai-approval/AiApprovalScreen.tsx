import { GearSix, Robot, SignOut, WarningCircle } from "@phosphor-icons/react";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useAuthenticatedClient } from "@posthog/ui/features/auth/authClient";
import { useLogoutMutation } from "@posthog/ui/features/auth/useAuthMutations";
import { authKeys } from "@posthog/ui/features/auth/useCurrentUser";
import { SHORTCUTS } from "@posthog/ui/features/command/keyboard-shortcuts";
import { openSettingsDialog } from "@posthog/ui/features/settings/SettingsDialog";
import { FullScreenLayout } from "@posthog/ui/primitives/FullScreenLayout";
import { track } from "@posthog/ui/shell/analytics";
import { Button, Callout, Flex, Spinner, Text } from "@radix-ui/themes";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { type ReactNode, useEffect } from "react";
import { useHotkeys } from "react-hotkeys-hook";

interface AiApprovalScreenProps {
  orgName: string | null;
  isAdmin: boolean;
  banner?: ReactNode;
  onOpenSupport?: () => void;
  settingsDialog?: ReactNode;
}

export function AiApprovalScreen({
  orgName,
  isAdmin,
  banner,
  onOpenSupport,
  settingsDialog,
}: AiApprovalScreenProps) {
  const logoutMutation = useLogoutMutation();
  const client = useAuthenticatedClient();
  const queryClient = useQueryClient();

  const approveMutation = useMutation({
    mutationFn: async () => {
      await client.approveAiDataProcessing();
    },
    onSuccess: async () => {
      track(ANALYTICS_EVENTS.AI_CONSENT_GRANTED_INAPP);
      await queryClient.invalidateQueries({
        queryKey: authKeys.currentUsers(),
      });
    },
  });

  // biome-ignore lint/correctness/useExhaustiveDependencies: fire once on mount; later isAdmin changes from query resolution should not re-fire
  useEffect(() => {
    track(ANALYTICS_EVENTS.AI_CONSENT_GATE_SHOWN, { is_org_admin: isAdmin });
  }, []);

  useHotkeys(SHORTCUTS.SETTINGS, () => openSettingsDialog(), {
    preventDefault: true,
    enableOnFormTags: true,
  });

  const footerLeft = (
    <Button
      size="1"
      variant="ghost"
      color="gray"
      onClick={() => openSettingsDialog()}
      className="opacity-70"
    >
      <GearSix size={14} />
      Settings
    </Button>
  );

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
    <>
      <FullScreenLayout
        footerLeft={footerLeft}
        footerRight={footerRight}
        banner={banner}
        onOpenSupport={onOpenSupport}
      >
        <Flex align="center" justify="center" height="100%" px="8">
          <Flex
            direction="column"
            className="w-full max-w-[560px] pt-[24px] pb-[40px]"
          >
            <motion.div
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3 }}
            >
              <Flex direction="column" gap="4">
                <Flex direction="column" gap="2">
                  <Flex align="center" gap="2">
                    <Robot
                      size={22}
                      weight="duotone"
                      color="var(--accent-10)"
                    />
                    <Text className="font-bold text-(--gray-12) text-2xl">
                      PostHog AI needs your approval
                    </Text>
                  </Flex>
                  <Text className="text-(--gray-11) text-sm">
                    {orgName ? (
                      <>
                        Your "<strong>{orgName}</strong>" organization hasn't
                        approved AI data processing yet.
                      </>
                    ) : (
                      "Your organization hasn't approved AI data processing yet."
                    )}
                  </Text>
                  <Text className="text-(--gray-11) text-sm">
                    PostHog AI features process identifying user data with
                    external AI providers.
                    <br />
                    Importantly: Your data won't be used for training models by
                    these providers.
                  </Text>
                </Flex>

                <Callout.Root color="amber" size="1" variant="soft">
                  <Callout.Icon>
                    <WarningCircle />
                  </Callout.Icon>
                  <Callout.Text>
                    <h4 className="mb-1 font-bold">
                      Legal bits about Protected Health Information
                    </h4>
                    This app isn't <i>yet</i> HIPAA-compliant and is not
                    intended for processing of Protected Health Information
                    ("PHI").
                    <br />
                    If you've entered into a Business Associate Agreement
                    ("BAA") with PostHog, it does not currently apply to PostHog
                    Code features.
                  </Callout.Text>
                </Callout.Root>

                {isAdmin ? (
                  <Flex direction="column" gap="2">
                    <Button
                      size="3"
                      onClick={() => approveMutation.mutate()}
                      disabled={approveMutation.isPending}
                      className="w-full"
                    >
                      {approveMutation.isPending ? (
                        <Spinner size="2" />
                      ) : (
                        "Approve AI data processing"
                      )}
                    </Button>
                    {approveMutation.isError && (
                      <Callout.Root color="red" size="1">
                        <Callout.Icon>
                          <WarningCircle />
                        </Callout.Icon>
                        <Callout.Text>
                          Could not approve AI data processing. Try again or
                          contact support.
                        </Callout.Text>
                      </Callout.Root>
                    )}
                  </Flex>
                ) : (
                  <Text className="text-(--gray-11) text-sm">
                    Ask an organization admin to approve AI data processing.
                  </Text>
                )}
              </Flex>
            </motion.div>
          </Flex>
        </Flex>
      </FullScreenLayout>
      {settingsDialog}
    </>
  );
}
