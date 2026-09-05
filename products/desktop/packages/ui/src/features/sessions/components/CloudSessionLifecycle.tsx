import { CloudSlash, Warning } from "@phosphor-icons/react";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import { Button, Flex, Text } from "@radix-ui/themes";

interface CloudStreamDisconnectedBannerProps {
  errorTitle?: string;
  errorMessage?: string;
  onRetry?: () => void;
  onRestart?: () => void;
}

export function CloudStreamDisconnectedBanner({
  errorTitle,
  errorMessage,
  onRetry,
  onRestart,
}: CloudStreamDisconnectedBannerProps) {
  return (
    <Flex
      align="center"
      justify="between"
      gap="3"
      py="2"
      px="3"
      className="shrink-0 border-(--red-5) border-b bg-(--red-2)"
    >
      <Flex align="center" gap="2" className="min-w-0">
        <Warning size={14} weight="duotone" color="var(--red-9)" />
        {errorTitle && (
          <Text className="shrink-0 font-medium text-(--red-12) text-[13px]">
            {errorTitle}
          </Text>
        )}
        {errorMessage && (
          <Text color="gray" className="truncate text-[13px]">
            {errorMessage}
          </Text>
        )}
      </Flex>
      <Flex gap="2">
        {onRetry && (
          <Button variant="soft" size="1" color="red" onClick={onRetry}>
            Retry
          </Button>
        )}
        {onRestart && (
          <Button variant="outline" size="1" onClick={onRestart}>
            Restart
          </Button>
        )}
      </Flex>
    </Flex>
  );
}

interface SandboxUnavailableBannerProps {
  onRetry?: () => void;
}

/**
 * A non-terminal cloud run whose sandbox the server reports as gone. Distinct
 * from the red error banner: the run has not failed, it is waiting for its
 * sandbox to come back, so this reads as amber "reconnecting" and keeps Retry
 * available. Stop stays in the task header throughout.
 */
export function SandboxUnavailableBanner({
  onRetry,
}: SandboxUnavailableBannerProps) {
  return (
    <Flex
      align="center"
      justify="between"
      gap="3"
      py="2"
      px="3"
      className="shrink-0 border-(--amber-5) border-b bg-(--amber-2)"
    >
      <Flex align="center" gap="2" className="min-w-0">
        <CloudSlash size={14} weight="duotone" color="var(--amber-9)" />
        <Text className="shrink-0 font-medium text-(--amber-12) text-[13px]">
          Sandbox unavailable
        </Text>
        <Text color="gray" className="truncate text-[13px]">
          Reconnecting to your cloud runner. Your messages send once it is back.
        </Text>
      </Flex>
      {onRetry && (
        <Button variant="soft" size="1" color="amber" onClick={onRetry}>
          Retry
        </Button>
      )}
    </Flex>
  );
}

export function ConnectingToAgent({ spinning = true }: { spinning?: boolean }) {
  return (
    <>
      <Spinner size={28} spinning={spinning} className="text-gray-9" />
      <Text color="gray" className="text-base">
        Connecting to agent...
      </Text>
    </>
  );
}
