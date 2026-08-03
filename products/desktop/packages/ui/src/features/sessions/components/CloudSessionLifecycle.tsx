import { Spinner, Warning } from "@phosphor-icons/react";
import { Button, Flex, Text } from "@radix-ui/themes";

interface CloudConnectionBannerProps {
  message: string;
}

export function CloudConnectionBanner({ message }: CloudConnectionBannerProps) {
  return (
    <Flex
      align="center"
      gap="2"
      py="2"
      px="3"
      className="shrink-0 border-gray-5 border-b bg-gray-2"
    >
      <Spinner size={14} className="animate-spin text-gray-9" />
      <Text color="gray" className="text-[13px]">
        {message}
      </Text>
    </Flex>
  );
}

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

export function ConnectingToAgent() {
  return (
    <>
      <Spinner size={28} className="animate-spin text-gray-9" />
      <Text color="gray" className="text-base">
        Connecting to agent...
      </Text>
    </>
  );
}
