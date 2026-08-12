import { CheckIcon, CopyIcon } from "@phosphor-icons/react";
import { useState } from "react";

/**
 * Copy-to-clipboard button with a transient check. Icon-only by default;
 * `bare` drops the border/background so it can nest inside another pill.
 */
export function CopyButton({
  text,
  label = "Copy",
  showLabel = false,
  bare = false,
}: {
  text: string;
  label?: string;
  showLabel?: boolean;
  bare?: boolean;
}) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard can be blocked (insecure context) — the text stays selectable.
    }
  }
  return (
    <button
      type="button"
      onClick={copy}
      aria-label={label}
      className={
        bare
          ? "inline-flex shrink-0 cursor-pointer items-center gap-1 rounded-(--radius-1) px-1 py-0.5 text-gray-10 transition-colors hover:bg-(--gray-4) hover:text-gray-12"
          : "inline-flex shrink-0 cursor-pointer items-center gap-1 rounded-(--radius-1) border border-border bg-(--color-panel-solid) px-1.5 py-0.5 text-[11px] text-gray-11 transition-colors hover:bg-(--gray-3) hover:text-gray-12"
      }
    >
      {copied ? (
        <CheckIcon size={12} className="text-(--green-11)" />
      ) : (
        <CopyIcon size={12} />
      )}
      {showLabel ? (copied ? "Copied" : label) : null}
    </button>
  );
}
