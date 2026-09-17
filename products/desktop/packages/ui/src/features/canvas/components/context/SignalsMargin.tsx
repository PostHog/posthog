import { ArrowSquareOutIcon, PulseIcon } from "@phosphor-icons/react";
import type { ContextObject } from "@posthog/core/canvas/contextDocument";
import type { SpaceSignal } from "@posthog/core/canvas/spaceSignals";
import { Text } from "@posthog/quill";
import { useSpaceSignals } from "@posthog/ui/features/canvas/hooks/useSpaceSignals";
import { getSourceProductMeta } from "@posthog/ui/features/inbox/components/utils/source-product-icons";
import { RelativeTimestamp } from "@posthog/ui/primitives/RelativeTimestamp";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";
import type { ReactNode } from "react";
import { SectionHeader } from "./SectionHeader";

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
      <SectionHeader
        label="Signals"
        action={
          <Text size="xs" variant="muted">
            last 7 days
          </Text>
        }
      />
      {objects.length === 0 ? (
        <SignalsNote>
          Link what this space owns and the signals about it show here.
        </SignalsNote>
      ) : isLoading ? (
        <SignalsNote leading={<Spinner size="xs" aria-hidden="true" />}>
          Reading signals
        </SignalsNote>
      ) : isError ? (
        <SignalsNote>Signals could not be read.</SignalsNote>
      ) : signals.length === 0 ? (
        <SignalsNote>
          Nothing about these objects in the last 7 days.
        </SignalsNote>
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

/**
 * One fact: where it came from and when on the first line, the fact under
 * it. When the source product said where it lives, the row opens it.
 */
function SignalRow({ signal }: { signal: SpaceSignal }) {
  const meta = getSourceProductMeta(signal.sourceProduct);
  const source = signal.sourceType
    ? humanize(signal.sourceType)
    : (meta?.label ?? humanize(signal.sourceProduct));
  const body = (
    <>
      <span className="flex items-center gap-1.5 text-muted-foreground text-xs">
        {meta ? (
          <meta.Icon size={11} className="shrink-0" />
        ) : (
          <PulseIcon size={11} className="shrink-0" />
        )}
        <span className="truncate">{source}</span>
        <span className="ml-auto flex shrink-0 items-center gap-1.5">
          {signal.url ? (
            <ArrowSquareOutIcon
              size={11}
              className="opacity-0 transition-opacity group-hover/signal:opacity-100 group-focus-visible/signal:opacity-100"
            />
          ) : null}
          {signal.timestamp ? (
            <RelativeTimestamp timestamp={signal.timestamp} />
          ) : null}
        </span>
      </span>
      <span className="line-clamp-4 text-foreground text-xs leading-snug">
        {signal.content}
      </span>
    </>
  );
  const url = signal.url;
  return (
    <li>
      {url ? (
        <button
          type="button"
          onClick={() => openExternalUrl(url)}
          className="group/signal flex w-full flex-col gap-1 rounded-md px-3 py-2.5 text-left transition-colors hover:bg-fill-hover"
        >
          {body}
        </button>
      ) : (
        <div className="flex flex-col gap-1 px-3 py-2.5">{body}</div>
      )}
    </li>
  );
}

function SignalsNote({
  leading,
  children,
}: {
  leading?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div className="flex items-center gap-2 border-border border-y px-3 py-4">
      {leading}
      <Text size="xs" variant="muted">
        {children}
      </Text>
    </div>
  );
}

function humanize(value: string): string {
  const words = value.replace(/[_-]+/g, " ").trim();
  if (!words) return "Signal";
  return words[0].toUpperCase() + words.slice(1);
}
