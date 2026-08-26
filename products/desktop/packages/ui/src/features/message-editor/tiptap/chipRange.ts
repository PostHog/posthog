import type { Node as PmNode } from "@tiptap/pm/model";

export interface ChipRange {
  from: number;
  to: number;
}

export function findChipRangeById(
  doc: PmNode,
  chipId: string,
): ChipRange | null {
  let range: ChipRange | null = null;
  doc.descendants((node, pos) => {
    if (range) return false;
    if (node.type.name !== "mentionChip") return;
    if (node.attrs.chipId !== chipId) return;
    const nodeEnd = pos + node.nodeSize;
    // Also swallow the trailing space the chip insertion added.
    const after = doc.textBetween(
      nodeEnd,
      Math.min(nodeEnd + 1, doc.content.size),
    );
    range = { from: pos, to: after === " " ? nodeEnd + 1 : nodeEnd };
    return false;
  });
  return range;
}
