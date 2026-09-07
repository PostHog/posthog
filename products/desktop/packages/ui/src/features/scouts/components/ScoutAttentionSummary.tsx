import {
  listScoutsNeedingDecision,
  type ScoutAttention,
} from "@posthog/core/scouts/scoutPresentation";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@posthog/quill";

/**
 * The fleet header count for agents the system stopped or is about to stop,
 * which names them on hover or focus. The number and the names come from one
 * list, so they cannot disagree.
 */
export function ScoutAttentionSummary({ items }: { items: ScoutAttention[] }) {
  if (items.length === 0) return null;

  const autoPausedCount = items.filter(
    (item) => item.kind === "auto_paused",
  ).length;
  const pausingSoonCount = items.filter(
    (item) => item.kind === "pausing_soon",
  ).length;
  const label = [
    autoPausedCount > 0 ? `${autoPausedCount} auto-paused` : null,
    pausingSoonCount > 0 ? `${pausingSoonCount} pausing soon` : null,
  ]
    .filter(Boolean)
    .join(" · ");
  const { entries, hiddenCount } = listScoutsNeedingDecision(items);

  return (
    <TooltipProvider delay={200}>
      <Tooltip>
        <TooltipTrigger
          render={
            <button
              type="button"
              className="cursor-default text-(--amber-11) underline decoration-dotted underline-offset-2"
              data-attr="scout-attention-count"
            >
              {label}
            </button>
          }
        />
        <TooltipContent side="top" align="end" className="max-w-84">
          <div className="flex flex-col gap-1.5">
            <p className="font-medium">Waiting on a decision</p>
            <ul className="flex flex-col gap-1">
              {entries.map((entry) => (
                <li key={entry.id} className="leading-snug">
                  <span className="font-medium">{entry.name}</span>{" "}
                  <span className="text-gray-11">{entry.reason}</span>
                </li>
              ))}
            </ul>
            {hiddenCount > 0 ? (
              <p className="text-gray-11">
                And {hiddenCount} more in the table below.
              </p>
            ) : null}
          </div>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
