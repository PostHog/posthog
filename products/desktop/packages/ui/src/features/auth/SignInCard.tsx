import type { CloudRegion } from "@posthog/shared";
import { OnboardingHogTip } from "@posthog/ui/primitives/OnboardingHogTip";
import { Flex, Text } from "@radix-ui/themes";
import { OAuthControls } from "./OAuthControls";

interface SignInCardProps {
  hogSrc: string;
  hogMessage: string;
  subtitle: string;
  onAuthInitiated?: (region: CloudRegion) => void;
  includeDevRegion?: boolean;
}

export function SignInCard({
  hogSrc,
  hogMessage,
  subtitle,
  onAuthInitiated,
  includeDevRegion = false,
}: SignInCardProps) {
  return (
    <Flex direction="column" gap="4">
      <Flex direction="column" gap="2">
        <Text className="font-bold text-(--gray-12) text-2xl">
          Sign in / sign up with PostHog
        </Text>
        <Text className="text-(--gray-11) text-sm">{subtitle}</Text>
      </Flex>
      <OAuthControls
        onAuthInitiated={onAuthInitiated}
        includeDevRegion={includeDevRegion}
      />
      <OnboardingHogTip hogSrc={hogSrc} message={hogMessage} />
    </Flex>
  );
}
