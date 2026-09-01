import type { UserBasic } from "@posthog/shared/domain-types";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";
import type { SuggestionItem } from "@posthog/ui/features/message-editor/types";
import type { Extension } from "@tiptap/core";
import { createDocSuggestion } from "./createDocSuggestion";

const MAX_PEOPLE_SUGGESTIONS = 8;

/** The id the agent entry carries; no person can hold it. */
export const AGENT_MENTION_ID = "__agent__";

/**
 * `@` in a doc: tags a person, or tags the agent.
 *
 * Tagging a person inserts Tiptap's own mention node, so the pill is part of the
 * document and every client draws it the same way. Tagging the agent inserts
 * nothing: it opens a thread beside the page, because the agent answers there
 * and never edits the doc.
 */
export function createDocPeopleMention(options: {
  sessionId: string;
  people: () => UserBasic[];
  onAskAgent: () => void;
}): Extension {
  return createDocSuggestion<SuggestionItem>({
    name: "docPeopleMention",
    sessionId: options.sessionId,
    char: "@",
    items: (query) => {
      const needle = query.trim().toLowerCase();
      const agentEntry: SuggestionItem = {
        id: AGENT_MENTION_ID,
        label: "Agent",
        description: "asks in a thread beside the page",
      };
      const people = options
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
          label: userDisplayName(person),
          description: person.email ?? undefined,
        }));

      const showAgent = !needle || "agent".startsWith(needle);
      return showAgent ? [agentEntry, ...people] : people;
    },
    onSelect: ({ editor, item }) => {
      if (item.id === AGENT_MENTION_ID) {
        options.onAskAgent();
        return;
      }
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
