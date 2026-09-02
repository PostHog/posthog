import { describe, expect, it } from "vitest";
import { agentAnswerToContent } from "./agentAnswer";

describe("agentAnswerToContent", () => {
  it("turns a cited query into a data point and keeps the words around it", () => {
    const content = agentAnswerToContent(
      'Teams this month: <hogql label="teams with replay">SELECT uniq(team_id) FROM events</hogql>.\n\nData ends on the 29th.',
    );

    expect(content).toEqual([
      {
        type: "paragraph",
        content: [
          { type: "text", text: "Teams this month: " },
          {
            type: "dataValue",
            attrs: {
              query: "SELECT uniq(team_id) FROM events",
              label: "teams with replay",
              note: "",
              requestId: "",
            },
          },
          { type: "text", text: "." },
        ],
      },
      {
        type: "paragraph",
        content: [{ type: "text", text: "Data ends on the 29th." }],
      },
    ]);
  });

  it("keeps a sketched query out of the page and leaves its label as words", () => {
    const content = agentAnswerToContent(
      'See <hogql label="teams with events">SELECT uniqExact(team_id) ...</hogql> for the count.',
    );

    expect(content).toEqual([
      {
        type: "paragraph",
        content: [
          { type: "text", text: "See teams with events for the count." },
        ],
      },
    ]);
  });
});
