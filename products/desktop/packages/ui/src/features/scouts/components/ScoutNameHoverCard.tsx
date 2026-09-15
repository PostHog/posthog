import { PreviewCard } from "@base-ui/react/preview-card";
import type { ScoutConfig } from "@posthog/api-client/posthog-client";
import { Card } from "@posthog/quill";
import type { ReactElement } from "react";

const OPEN_DELAY_MS = 400;
const CLOSE_DELAY_MS = 100;

/**
 * The agent's full description, shown while the pointer rests on its name in
 * the list. The row itself stays one line; the card carries the prose.
 */
export function ScoutNameHoverCard({
  config,
  trigger,
}: {
  config: ScoutConfig;
  /** The name link. Rendered as the card's trigger. */
  trigger: ReactElement;
}) {
  const description = config.description?.trim();
  if (!description) return trigger;
  return (
    <PreviewCard.Root>
      <PreviewCard.Trigger
        render={trigger}
        delay={OPEN_DELAY_MS}
        closeDelay={CLOSE_DELAY_MS}
      />
      <PreviewCard.Portal>
        <PreviewCard.Positioner
          side="bottom"
          align="start"
          sideOffset={6}
          className="z-50"
        >
          <PreviewCard.Popup
            render={
              <Card
                size="sm"
                className="w-96 gap-0 border border-border py-0 shadow-md"
              />
            }
          >
            <div className="flex flex-col gap-2 px-3.5 py-3">
              <p className="max-h-80 overflow-y-auto text-pretty text-[12.5px] text-gray-12 leading-relaxed">
                {description}
              </p>
              <code className="truncate text-[11px] text-gray-10">
                {config.skill_name}
              </code>
            </div>
          </PreviewCard.Popup>
        </PreviewCard.Positioner>
      </PreviewCard.Portal>
    </PreviewCard.Root>
  );
}
