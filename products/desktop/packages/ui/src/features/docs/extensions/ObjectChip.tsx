import { createInlineRef } from "./inline/createInlineRef";
import { type ObjectRefAttrs, objectRef } from "./inline/kinds/objectRef";

export type ObjectChipAttrs = ObjectRefAttrs;

export const ObjectChip = createInlineRef(objectRef);
