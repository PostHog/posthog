import { createInlineRef } from "./inline/createInlineRef";
import { type PersonRefAttrs, personRef } from "./inline/kinds/personRef";

export type PersonMentionAttrs = PersonRefAttrs;

export const PersonMention = createInlineRef(personRef);
