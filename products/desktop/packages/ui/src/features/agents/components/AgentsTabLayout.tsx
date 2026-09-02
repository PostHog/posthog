import { RobotIcon } from "@phosphor-icons/react";
import { useSetHeaderContent } from "@posthog/ui/hooks/useSetHeaderContent";
import { type ReactNode, useMemo } from "react";

export function AgentsTabLayout({ children }: { children: ReactNode }) {
  const headerContent = useMemo(
    () => (
      <div className="flex w-full min-w-0 items-center gap-2">
        <RobotIcon size={12} className="shrink-0 text-gray-10" />
        <span
          className="truncate whitespace-nowrap font-medium text-[13px]"
          title="Agents"
        >
          Agents
        </span>
      </div>
    ),
    [],
  );
  useSetHeaderContent(headerContent);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="cursor-default select-none border-(--gray-5) border-b px-6 py-5">
        <div className="flex flex-col gap-0.5">
          <h1 className="font-bold text-[22px] text-gray-12 leading-tight tracking-tight">
            Agents
          </h1>
          <p className="max-w-3xl text-[12.5px] text-gray-11 leading-snug">
            Self-driving agents that watch your project and surface work for
            review.
          </p>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-auto">
        <div className="mx-auto max-w-4xl px-6 py-6">{children}</div>
      </div>
    </div>
  );
}
