import type { FileHrefTarget } from "@posthog/core/code-editor/fileHref";
import { parseFileHref } from "@posthog/core/code-editor/fileHref";
import { useFileLinkOpener } from "@posthog/ui/features/code-editor/useFileLinkOpener";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import type { ReactElement, ReactNode } from "react";

/**
 * A markdown link whose href names a file opens it in a split panel, because a
 * browser resolves the path against the app's own origin and lands on a 404
 * instead. Where no file would resolve — no task is in scope, or its workspace
 * is gone — the label renders as plain text rather than as a dead-end link.
 */
function MarkdownFileLink({
  target,
  children,
}: {
  target: FileHrefTarget;
  children: ReactNode;
}) {
  const openFile = useFileLinkOpener("markdown-link");
  if (!openFile) return <>{children}</>;

  const label = target.line ? `${target.path}:${target.line}` : target.path;
  return (
    <Tooltip content={label}>
      <button
        type="button"
        onClick={() => openFile(target)}
        className="markdown-link m-0 inline border-0 bg-transparent p-0 text-left font-[inherit] text-[length:inherit]"
      >
        {children}
      </button>
    </Tooltip>
  );
}

/**
 * The in-app file link a markdown href renders as, or null when the href points
 * at a web page. Shared so both markdown renderers route file targets the same
 * way.
 */
export function fileLinkFor(
  href: string | undefined,
  children: ReactNode,
): ReactElement | null {
  const target = parseFileHref(href);
  if (!target) return null;
  return <MarkdownFileLink target={target}>{children}</MarkdownFileLink>;
}
