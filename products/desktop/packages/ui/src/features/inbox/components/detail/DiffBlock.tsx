// Renders unified-diff text with per-line +/- coloring, used by the `commit`
// artefact's commit-vs-parent diff view.
export function DiffBlock({ diff }: { diff: string }) {
  const lines = diff.replace(/\n$/, "").split("\n");
  return (
    <pre className="max-h-96 overflow-auto rounded-(--radius-3) border border-(--gray-6) bg-(--gray-2) p-2 font-mono text-[11px] leading-[1.5]">
      {lines.map((line, i) => {
        const added = line.startsWith("+") && !line.startsWith("+++");
        const removed = line.startsWith("-") && !line.startsWith("---");
        const hunk = line.startsWith("@@");
        const cls = added
          ? "bg-(--green-3) text-(--green-11)"
          : removed
            ? "bg-(--red-3) text-(--red-11)"
            : hunk
              ? "text-(--gray-10)"
              : "text-(--gray-12)";
        return (
          // biome-ignore lint/suspicious/noArrayIndexKey: stable parse output, never reorders
          <div key={i} className={cls}>
            {line || " "}
          </div>
        );
      })}
    </pre>
  );
}
