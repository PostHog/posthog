import { IssueRow } from "../components/IssueRow";
import { getIssueSuggestions } from "../suggestions/getSuggestions";
import { createSuggestionMention } from "./createSuggestionMention";

export function createIssueMention(sessionId: string) {
  return createSuggestionMention({
    name: "issueMention",
    sessionId,
    char: "#",
    chipType: "github_issue",
    debounceMs: 250,
    items: (query) => (sessionId ? getIssueSuggestions(sessionId, query) : []),
    renderItem: (item) => <IssueRow issue={item} />,
  });
}
