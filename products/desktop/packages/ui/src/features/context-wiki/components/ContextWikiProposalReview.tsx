import { MultiFileDiff } from "@pierre/diffs/react";
import { requestErrorStatus } from "@posthog/api-client/fetcher";
import type { ContextWikiPageProposal } from "@posthog/api-client/posthog-client";
import { Button } from "@posthog/quill";
import { DIFFS_HIGHLIGHTER_OPTIONS } from "@posthog/ui/features/sessions/diffHighlighterOptions";
import { useThemeStore } from "@posthog/ui/shell/themeStore";
import { type ReactElement, useMemo } from "react";

export function ContextWikiProposalReview({
  proposal,
  applying,
  applied,
  error,
  onApply,
}: {
  proposal: ContextWikiPageProposal;
  applying: boolean;
  applied: boolean;
  error: Error | null;
  onApply: () => void;
}): ReactElement {
  const conflict = requestErrorStatus(error) === 409;
  const isDarkMode = useThemeStore((state) => state.isDarkMode);
  const options = useMemo(
    () => ({
      ...DIFFS_HIGHLIGHTER_OPTIONS,
      diffStyle: "unified" as const,
      overflow: "wrap" as const,
      expandUnchanged: true,
      themeType: (isDarkMode ? "dark" : "light") as "dark" | "light",
    }),
    [isDarkMode],
  );

  return (
    <section className="flex min-h-0 min-w-0 flex-1 flex-col gap-3 overflow-auto p-4">
      <h2 className="break-all font-medium">{proposal.path}</h2>
      <p className="text-(--gray-11) text-sm">
        This edit is not published. Review all changes before you apply it to
        the shared wiki.
      </p>
      <MultiFileDiff
        oldFile={{ name: proposal.path, contents: proposal.original_content }}
        newFile={{ name: proposal.path, contents: proposal.content }}
        options={options}
      />
      {error ? (
        <p role="alert" className="text-(--red-11) text-sm">
          {conflict
            ? "The wiki changed. Ask the task to read the page again and submit a new edit."
            : "Could not apply this edit. Check your wiki write permission and the page format, then try again."}
        </p>
      ) : null}
      <div>
        <Button
          variant="primary"
          disabled={applying || applied || conflict}
          onClick={onApply}
        >
          {applying
            ? "Applying…"
            : applied
              ? "Applied"
              : "Apply to shared wiki"}
        </Button>
      </div>
    </section>
  );
}
