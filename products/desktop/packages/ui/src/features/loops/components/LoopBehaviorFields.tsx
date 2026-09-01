import type { LoopSchemas } from "@posthog/api-client/loops";
import { Switch } from "@posthog/quill";
import { Flex, Text } from "@radix-ui/themes";
import { isAutoFixEnabled, withAutoFix } from "../loopFormTypes";

interface LoopBehaviorFieldsProps {
  behaviors: LoopSchemas.LoopBehaviors;
  onChange: (behaviors: LoopSchemas.LoopBehaviors) => void;
  disabled?: boolean;
}

export function LoopBehaviorFields({
  behaviors,
  onChange,
  disabled,
}: LoopBehaviorFieldsProps) {
  return (
    <Flex
      direction="column"
      gap="2"
      className="rounded-(--radius-2) border border-border bg-(--gray-1) p-3"
    >
      <Flex align="center" justify="between" gap="2">
        <Flex direction="column" gap="0">
          <Text className="font-medium text-[13px] text-gray-12">
            Auto-fix pull requests
          </Text>
          <Text className="text-[12px] text-gray-10">
            Watch CI and review comments on PRs this loop opens, and let PostHog
            push fixes.
          </Text>
        </Flex>
        <Switch
          checked={isAutoFixEnabled(behaviors)}
          disabled={disabled}
          aria-label="Auto-fix pull requests"
          onCheckedChange={(checked) =>
            onChange(withAutoFix(behaviors, checked))
          }
        />
      </Flex>
    </Flex>
  );
}
