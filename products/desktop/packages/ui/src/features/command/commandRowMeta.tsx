import { Fragment, type ReactNode } from "react";

export type CommandRowMetaPart = { text: string; title?: string };

export function commandRowMeta(
  parts: (CommandRowMetaPart | undefined)[],
): ReactNode | undefined {
  const shown = parts.filter((part): part is CommandRowMetaPart =>
    Boolean(part?.text.trim()),
  );
  if (shown.length === 0) return undefined;
  return shown.map((part, index) => (
    <Fragment key={part.text}>
      {index > 0 ? " · " : null}
      <span title={part.title}>{part.text.trim()}</span>
    </Fragment>
  ));
}
