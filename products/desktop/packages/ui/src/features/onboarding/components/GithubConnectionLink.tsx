import { GithubLogo } from "@phosphor-icons/react";
import { cn } from "@posthog/quill";
import Logo from "@posthog/ui/primitives/Logo";
import { Flex, Text } from "@radix-ui/themes";
import type { ReactNode } from "react";

function Tile({ children }: { children: ReactNode }) {
  return (
    <Flex
      align="center"
      justify="center"
      className="size-[48px] shrink-0 rounded-[12px] border border-(--gray-a4) bg-(--color-panel-solid)"
    >
      {children}
    </Flex>
  );
}

interface GithubConnectionLinkProps {
  connected: boolean;
  /** Shown under the link once a connection exists. */
  accountLabel?: string | null;
}

/** The link between the two marks carries the connection state. */
export function GithubConnectionLink({
  connected,
  accountLabel,
}: GithubConnectionLinkProps) {
  return (
    <Flex direction="column" align="center" gap="2">
      <Flex align="center">
        <Tile>
          <span className="[&>svg]:h-[17px] [&>svg]:w-auto">
            <Logo wordmark={false} />
          </span>
        </Tile>
        <div
          className={cn(
            "w-[56px] border-t-2 transition-colors duration-300",
            connected
              ? "border-(--green-9) border-solid"
              : "border-(--gray-a6) border-dashed",
          )}
        />
        <Tile>
          <GithubLogo
            size={26}
            weight="fill"
            className={cn(
              "transition-colors duration-300",
              connected ? "text-(--gray-12)" : "text-(--gray-9)",
            )}
          />
        </Tile>
      </Flex>
      {connected && accountLabel && (
        <Text className="text-(--green-11) text-[13px]">{accountLabel}</Text>
      )}
    </Flex>
  );
}
