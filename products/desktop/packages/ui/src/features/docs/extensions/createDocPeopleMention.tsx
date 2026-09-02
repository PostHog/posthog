import type { UserBasic } from "@posthog/shared/domain-types";
import { UserAvatar } from "@posthog/ui/features/auth/UserAvatar";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";
import type { Extension } from "@tiptap/core";
import { createDocSuggestion } from "./createDocSuggestion";
import type { DocSuggestionItem } from "./DocSuggestionList";

const MAX_PEOPLE_SUGGESTIONS = 8;

/**
 * `@` in a doc: tags a person.
 *
 * The pill marks who a line is for and nothing else happens. Asking the agent is
 * a different act with a different shape: select the words and use the toolbar.
 */
export function createDocPeopleMention(options: {
  sessionId: string;
  people: () => UserBasic[];
}): Extension {
  return createDocSuggestion<DocSuggestionItem>({
    name: "docPeopleMention",
    sessionId: options.sessionId,
    char: "@",
    emptyMessage: "Nobody by that name",
    items: (query) => {
      const needle = query.trim().toLowerCase();
      return options
        .people()
        .filter((person) => {
          if (!needle) return true;
          const name = userDisplayName(person).toLowerCase();
          return (
            name.includes(needle) ||
            (person.email ?? "").toLowerCase().includes(needle)
          );
        })
        .slice(0, MAX_PEOPLE_SUGGESTIONS)
        .map((person) => ({
          id: person.uuid ?? String(person.id ?? ""),
          icon: <UserAvatar user={person} size="xs" />,
          label: userDisplayName(person),
          description: person.email ?? undefined,
        }));
    },
    onSelect: ({ editor, item }) => {
      editor
        .chain()
        .focus()
        .insertContent([
          { type: "mention", attrs: { id: item.id, label: item.label } },
          { type: "text", text: " " },
        ])
        .run();
    },
  });
}
