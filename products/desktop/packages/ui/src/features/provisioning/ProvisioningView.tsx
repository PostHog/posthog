import { Box, Flex, Spinner, Text } from "@radix-ui/themes";
import { useEffect, useRef } from "react";
import { useProvisioningStore } from "./store";

interface ProvisioningViewProps {
  taskId: string;
}

export function ProvisioningView({ taskId }: ProvisioningViewProps) {
  const lines = useProvisioningStore((s) => s.output[taskId]);
  const scrollRef = useRef<HTMLPreElement>(null);

  const text = (lines ?? []).join("\n");

  useEffect(() => {
    const el = scrollRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, []);

  return (
    <Box height="100%">
      <Flex direction="column" height="100%" p="3" gap="2">
        <Flex align="center" gap="2">
          <Spinner size="1" />
          <Text className="font-medium text-[13px]">
            Setting up worktree...
          </Text>
        </Flex>
        <Box className="min-h-0 flex-1 rounded-(--radius-2) border border-(--gray-a5) bg-(--color-surface)">
          <pre
            ref={scrollRef}
            className="m-0 h-full overflow-auto whitespace-pre-wrap break-all p-2 font-[var(--code-font-family)] text-(--gray-12) text-[13px]"
          >
            {text}
          </pre>
        </Box>
      </Flex>
    </Box>
  );
}
