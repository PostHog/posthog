import { ArrowClockwise, Check, X } from "@phosphor-icons/react";
import { useService } from "@posthog/di/react";
import {
  getActionSessionId,
  useActionStore,
} from "@posthog/ui/features/actions/actionStore";
import {
  SHELL_CLIENT,
  type ShellClient,
} from "@posthog/ui/features/terminal/shellClient";
import { terminalManager } from "@posthog/ui/features/terminal/TerminalManager";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import { Spinner } from "@radix-ui/themes";
import { useCallback, useState } from "react";

interface ActionTabIconProps {
  actionId: string;
}

export function ActionTabIcon({ actionId }: ActionTabIconProps) {
  const [hovered, setHovered] = useState(false);
  const shellClient = useService<ShellClient>(SHELL_CLIENT);
  const status = useActionStore((state) => state.statuses[actionId]);
  const generation = useActionStore(
    (state) => state.generations[actionId] ?? 0,
  );
  const rerun = useActionStore((state) => state.rerun);

  const triggerRerun = useCallback(() => {
    const sessionId = getActionSessionId(actionId, generation);
    terminalManager.destroy(sessionId);
    shellClient.destroy({ sessionId });
    rerun(actionId);
  }, [actionId, generation, rerun, shellClient]);

  const handleClick = useCallback(
    (e: React.MouseEvent) => {
      if (!hovered) return;
      e.stopPropagation();
      triggerRerun();
    },
    [hovered, triggerRerun],
  );

  let icon: React.ReactNode;
  if (hovered) {
    icon = <ArrowClockwise size={14} weight="bold" />;
  } else if (status === "success") {
    icon = <Check size={14} weight="bold" className="text-green-9" />;
  } else if (status === "error") {
    icon = <X size={14} weight="bold" className="text-red-9" />;
  } else {
    icon = <Spinner size="1" />;
  }

  const content = (
    <button
      type="button"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onClick={handleClick}
      style={{
        cursor: hovered ? "pointer" : undefined,
        color: "inherit",
      }}
      className="m-0 flex items-center border-0 bg-transparent p-0"
    >
      {icon}
    </button>
  );

  if (hovered) {
    return (
      <Tooltip content="Rerun action" side="bottom">
        {content}
      </Tooltip>
    );
  }

  return content;
}
