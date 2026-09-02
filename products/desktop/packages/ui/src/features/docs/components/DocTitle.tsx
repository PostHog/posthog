import { useEffect, useState } from "react";

/** How many minutes count as "now" in the meta line. */
const JUST_NOW_MINUTES = 2;

function editedLabel(updatedAt: string): string {
  const then = new Date(updatedAt).getTime();
  if (!Number.isFinite(then)) return "edited";
  const minutes = Math.floor((Date.now() - then) / 60_000);
  if (minutes < JUST_NOW_MINUTES) return "edited now";
  if (minutes < 60) return `edited ${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `edited ${hours}h ago`;
  return `edited ${Math.floor(hours / 24)}d ago`;
}

/**
 * The doc's title and the line under it.
 *
 * The title belongs to the page, not to a toolbar, so it reads as the first
 * thing in the document. It stays editable in place.
 */
export function DocTitle({
  title,
  peopleCount,
  updatedAt,
  onRename,
}: {
  title: string;
  peopleCount: number;
  updatedAt: string;
  onRename: (title: string) => void;
}) {
  const [draft, setDraft] = useState(title);
  useEffect(() => setDraft(title), [title]);

  const commit = () => {
    const next = draft.trim();
    if (next !== title) onRename(next);
  };

  return (
    <div className="doc-page-head pt-1 pb-3">
      <input
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.preventDefault();
            event.currentTarget.blur();
          }
        }}
        aria-label="Doc title"
        placeholder="Untitled"
        className="doc-title w-full border-none bg-transparent p-0 text-(--gray-12) outline-none placeholder:text-(--gray-9)"
      />
      <div className="mt-1.5 flex items-center gap-[9px] text-(--gray-9) text-xs">
        <span>
          {peopleCount} {peopleCount === 1 ? "person" : "people"}
        </span>
        <span className="size-[3px] rounded-full bg-(--gray-7)" />
        <span>{editedLabel(updatedAt)}</span>
      </div>
    </div>
  );
}
