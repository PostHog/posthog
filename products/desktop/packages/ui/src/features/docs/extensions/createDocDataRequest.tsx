import { ChartLineIcon } from "@phosphor-icons/react";
import { DocMark } from "@posthog/ui/primitives/DocMark";
import type { Editor, Extension } from "@tiptap/core";
import { createDocSuggestion } from "./createDocSuggestion";
import type { DocSuggestionItem } from "./DocSuggestionList";

type DataChoice =
  /** A saved insight the page can read a data point from at once. */
  | { kind: "insight"; shortId: string; label: string }
  /** Nothing saved fits, so the agent writes the query for it. */
  | { kind: "ask"; question: string };

interface DataRequestItem extends DocSuggestionItem {
  choice: DataChoice;
}

const EXAMPLES = [
  "weekly signups by country",
  "how many teams turned on replay this month",
  "activation rate since the new setup screen",
];

const MAX_MATCHES = 5;
/** How long the popup waits for saved insights before it shows the ask row alone. */
const SEARCH_GRACE_MS = 120;

type Insight = { shortId: string; label: string };

/**
 * Saved insights, answered at once from what was already found.
 *
 * The ask row must never wait for a search: a person types a question and
 * presses Enter. A search that is still running fills the list in on the next
 * keystroke, and a query already searched comes back with no request at all.
 */
function createInsightLookup(search: (query: string) => Promise<Insight[]>) {
  const found = new Map<string, Insight[]>();
  const inFlight = new Map<string, Promise<Insight[]>>();
  return async (query: string): Promise<Insight[]> => {
    const known = found.get(query);
    if (known) return known;
    let pending = inFlight.get(query);
    if (!pending) {
      pending = search(query)
        .then((insights) => {
          found.set(query, insights);
          return insights;
        })
        .catch(() => [])
        .finally(() => inFlight.delete(query));
      inFlight.set(query, pending);
    }
    const grace = new Promise<Insight[]>((resolve) =>
      setTimeout(() => resolve([]), SEARCH_GRACE_MS),
    );
    return Promise.race([pending, grace]);
  };
}

/**
 * `+` in a doc: ask for a data point in your own words.
 *
 * What the project already measures comes back as you type, and picking one puts
 * the data point in the sentence at once, with nothing to wait for. The agent is
 * the answer to "nothing here measures that yet", not the first step.
 */
export function createDocDataRequest(options: {
  sessionId: string;
  /** Saved insights matching a search. */
  insights: (
    query: string,
  ) => Promise<Array<{ shortId: string; label: string }>>;
  onPick: (choice: DataChoice, editor: Editor) => void;
}): Extension {
  const lookup = createInsightLookup(options.insights);
  return createDocSuggestion<DataRequestItem>({
    name: "docDataRequest",
    sessionId: options.sessionId,
    char: "+",
    startOfLine: false,
    allowSpaces: true,
    debounceMs: 150,
    emptyMessage: "Type what you want to see",
    items: async (query) => {
      const question = query.trim();
      if (!question) {
        return EXAMPLES.map((example) => ({
          id: example,
          group: "Ask in your own words",
          icon: <DocMark variant="agent" state="still" size={13} />,
          label: example,
          choice: { kind: "ask", question: example },
        }));
      }

      const matches = await lookup(question);
      const saved: DataRequestItem[] = matches
        .slice(0, MAX_MATCHES)
        .map((insight) => ({
          id: insight.shortId,
          group: "Already measured",
          icon: <ChartLineIcon size={15} />,
          label: insight.label,
          description: "saved insight",
          choice: {
            kind: "insight",
            shortId: insight.shortId,
            label: insight.label,
          },
        }));

      return [
        ...saved,
        {
          id: "ask",
          group: "Ask the agent",
          icon: <DocMark variant="agent" state="still" size={13} />,
          label: question,
          description: "it writes the query",
          hint: "↵",
          choice: { kind: "ask", question },
        },
      ];
    },
    onSelect: ({ editor, item }) => options.onPick(item.choice, editor),
  });
}
