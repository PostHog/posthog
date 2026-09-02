import type { Icon } from "@phosphor-icons/react";
import type { ReactElement } from "react";

const SIZE = 12;

/** The kind glyph an inline reference carries, at the size the prose expects. */
export function DocRefIcon({ icon: Glyph }: { icon: Icon }): ReactElement {
  return <Glyph size={SIZE} className="text-(--gray-10)" aria-hidden />;
}
