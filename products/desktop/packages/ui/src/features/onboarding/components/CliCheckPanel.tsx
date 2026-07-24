import { CheckCircle, CircleNotch } from "@phosphor-icons/react";
import { PANEL_SHADOW } from "@posthog/ui/features/onboarding/components/onboardingStyles";
import { Box, Flex, Text } from "@radix-ui/themes";
import type { ReactNode } from "react";

interface CliCheckPanelProps {
  icon: ReactNode;
  title: string;
  isLoading: boolean;
  statusBadge: ReactNode | null;
  children?: ReactNode;
}

export function CliCheckPanel({
  icon,
  title,
  isLoading,
  statusBadge,
  children,
}: CliCheckPanelProps) {
  return (
    <Box
      p="5"
      style={{ boxShadow: PANEL_SHADOW }}
      className="rounded-[12px] border border-(--gray-a3) bg-(--color-panel-solid)"
    >
      <Flex direction="column" gap="3">
        <Flex align="center" justify="between">
          <Flex align="center" gap="2">
            {icon}
            <Text className="font-bold text-(--gray-12) text-base">
              {title}
            </Text>
          </Flex>
          {isLoading ? (
            <CircleNotch size={14} className="animate-spin text-(--gray-9)" />
          ) : (
            statusBadge
          )}
        </Flex>
        {children}
      </Flex>
    </Box>
  );
}

interface InstalledBadgeProps {
  label: string;
}

export function InstalledBadge({ label }: InstalledBadgeProps) {
  return (
    <Flex align="center" gap="1">
      <CheckCircle size={14} weight="fill" className="text-(--green-9)" />
      <Text className="text-(--green-11) text-[13px]">{label}</Text>
    </Flex>
  );
}
