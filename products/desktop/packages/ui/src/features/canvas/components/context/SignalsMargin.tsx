import type { ContextObject } from "@posthog/core/canvas/contextDocument";
import type { SpaceSignal } from "@posthog/core/canvas/spaceSignals";
import { Text } from "@posthog/quill";
import { useSpaceSignals } from "@posthog/ui/features/canvas/hooks/useSpaceSignals";
import { getSourceProductMeta } from "@posthog/ui/features/inbox/components/utils/source-product-icons";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { Spinner } from "@posthog/ui/primitives/Spinner";

interface SignalsMarginProps {
  objects: ContextObject[];
}

/**
 * The raw signals scouts and source products filed about the objects this
 * space watches, newest first. Facts, not reports: a report is a judgement
 * and lives in the space's Reports tab.
 */
export function SignalsMargin({ objects }: SignalsMarginProps) {
  const { data, isLoading, isError } = useSpaceSignals(objects);
  const signals = data ?? [];

  return (
    <section className="flex flex-col gap-2">
      <div className="flex items-baseline justify-between gap-2">
        <Text size="xs" weight="medium" variant="muted">
          Signals
        </Text>
        <Text size="xxs" variant="muted">
          last 7 days
        </Text>
      </div>
      {objects.length === 0 ? (
        <Text size="xxs" variant="muted">
          Link what this space owns and the signals about it show here.
        </Text>
      ) : isLoading ? (
        <div className="flex items-center gap-2 py-1">
          <Spinner size="xs" aria-hidden="true" />
          <Text size="xxs" variant="muted">
            Reading signals
          </Text>
        </div>
      ) : isError ? (
        <Text size="xxs" variant="muted">
          Signals could not be read.
        </Text>
      ) : signals.length === 0 ? (
        <Text size="xxs" variant="muted">
          Nothing about these objects in the last 7 days.
        </Text>
      ) : (
        <ul className="flex flex-col divide-y divide-border border-border border-y">
          {signals.map((signal, index) => (
            <SignalRow
              key={`${signal.sourceId}-${signal.timestamp}-${index}`}
              signal={signal}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

/** One fact: where it came from and when on the first line, the fact under it. */
function SignalRow({ signal }: { signal: SpaceSignal }) {
  const meta = getSourceProductMeta(signal.sourceProduct);
  const source = signal.sourceType
    ? humanize(signal.sourceType)
    : (meta?.label ?? humanize(signal.sourceProduct));
  return (
    <li className="flex flex-col gap-1 py-2.5">
      <span className="flex items-center gap-1.5 text-muted-foreground text-xxs">
        {meta ? <meta.Icon size={11} className="shrink-0" /> : null}
        <span className="truncate">{source}</span>
        {signal.timestamp ? (
          <span className="ml-auto shrink-0">
            <RelativeTimestamp timestamp={signal.timestamp} />
          </span>
        ) : null}
      </span>
      <span className="line-clamp-4 text-foreground text-xs leading-snug">
        {signal.content}
      </span>
    </li>
  );
}

function humanize(value: string): string {
  const words = value.replace(/[_-]+/g, " ").trim();
  if (!words) return "Signal";
  return words[0].toUpperCase() + words.slice(1);
}
