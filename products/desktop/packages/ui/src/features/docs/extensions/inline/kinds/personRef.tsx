import { useOrgMembers } from "@posthog/ui/features/canvas/hooks/useOrgMembers";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";
import Mention from "@tiptap/extension-mention";
import type { InlineRefKind, InlineRefState } from "../types";

export interface PersonRefAttrs {
  id: string;
  label: string;
}

function initial(name: string): string {
  return (name.trim()[0] ?? "?").toUpperCase();
}

function usePersonRef({ id, label }: PersonRefAttrs): InlineRefState {
  const { members } = useOrgMembers();
  const person = members.find(
    (member) => member.uuid === id || String(member.id) === id,
  );
  const name = person ? userDisplayName(person) : label || "Someone";

  return {
    label: name,
    mark: <span className="doc-ref-avatar">{initial(name)}</span>,
    card: person?.email
      ? { title: name, meta: <span>{person.email}</span> }
      : undefined,
  };
}

/**
 * A person tagged with `@`.
 *
 * The node keeps the name and the attributes `@` writes, so the suggestion
 * plugin and every stored doc are unaffected; only the rendering changes.
 */
export const personRef: InlineRefKind<PersonRefAttrs> = {
  name: "mention",
  base: Mention,
  attributes: { id: { default: "" }, label: { default: "" } },
  parseTag: "span[data-type='mention']",
  domAttributes: ({ id }) => ({ "data-type": "mention", "data-id": id }),
  fallbackLabel: ({ label }) => `@${label}`,
  useRef: usePersonRef,
};
