import type { LoopSchemas } from "@posthog/api-client/loops";
import { Switch } from "@posthog/quill";
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
    <div className="flex flex-col gap-2 rounded-(--radius-2) border border-border bg-(--gray-1) p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="flex flex-col gap-0">
          <span className="font-medium text-[13px] text-gray-12">
            Auto-fix pull requests
          </span>
          <span className="text-[12px] text-gray-10">
            Watch CI and review comments on PRs this loop opens, and let PostHog
            push fixes.
          </span>
        </div>
        <Switch
          checked={isAutoFixEnabled(behaviors)}
          disabled={disabled}
          aria-label="Auto-fix pull requests"
          onCheckedChange={(checked) =>
            onChange(withAutoFix(behaviors, checked))
          }
        />
      </div>
    </div>
  );
}
