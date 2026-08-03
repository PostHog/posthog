import { Info, X } from "@phosphor-icons/react";
import { useState } from "react";
import { useScoutMetadata } from "../hooks/useScoutMetadata";

const DISMISS_KEY_PREFIX = "scout-alpha-banner-dismissed:";

const dismissKeyFor = (message: string): string =>
  `${DISMISS_KEY_PREFIX}${message}`;

/**
 * Alpha/announcement banner for the scout fleet, sourced from the `signals-scout` flag via the
 * metadata endpoint — so the copy (e.g. a run-limit notice) changes with no app release. Renders
 * nothing when no message is set. Dismissal is remembered per-message, so a reworded notice
 * resurfaces. localStorage is read during render against the current message, which keeps it
 * correct even though the message arrives after the first paint.
 */
export function ScoutAlphaBanner() {
  const { data: metadata } = useScoutMetadata();
  const message = metadata?.banner_message ?? null;
  const [dismissedKeys, setDismissedKeys] = useState<Set<string>>(
    () => new Set(),
  );

  if (!message) {
    return null;
  }

  const key = dismissKeyFor(message);
  if (dismissedKeys.has(key) || localStorage.getItem(key) === "1") {
    return null;
  }

  const dismiss = () => {
    localStorage.setItem(key, "1");
    setDismissedKeys((prev) => new Set(prev).add(key));
  };

  return (
    <div className="flex w-full items-start gap-2.5 rounded-(--radius-2) border border-(--blue-6) bg-(--blue-2) px-3.5 py-2.5 text-(--blue-11) text-[12.5px]">
      <Info size={16} weight="duotone" className="mt-px shrink-0" />
      <span className="min-w-0 flex-1 leading-snug">{message}</span>
      <button
        type="button"
        aria-label="Dismiss"
        onClick={dismiss}
        className="-mr-1 shrink-0 rounded-(--radius-1) p-0.5 text-(--blue-11) transition-colors hover:bg-(--blue-4)"
      >
        <X size={14} />
      </button>
    </div>
  );
}
