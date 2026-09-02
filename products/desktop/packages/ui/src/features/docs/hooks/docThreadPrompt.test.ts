import { describe, expect, it } from "vitest";
import {
  dataPointTaskInput,
  stripAgentMention,
  threadTaskInput,
  watchTaskInput,
} from "./docThreadPrompt";

describe("docThreadPrompt", () => {
  it("strips the tag and carries the thread into the task", () => {
    const input = threadTaskInput({
      anchorText: "Replay went on for the team",
      lines: [{ author: "Shy", content: "Is this still true?" }],
      question: "@agent which teams?",
      docTitle: "Super",
    });

    expect(input.question).toBe("which teams?");
    expect(input.description).toContain("“Replay went on for the team”");
    expect(input.description).toContain("Shy: Is this still true?");
    expect(input.description).not.toContain("@agent");
  });

  it("names the request id and the skill for a data point", () => {
    const input = dataPointTaskInput({
      question: "pageviews",
      requestId: "r1",
      docTitle: "Super",
    });

    expect(input.description).toContain("request_id: r1");
    expect(input.description).toContain("call doc-data-point-submit");
  });

  it.each([
    ["@agent hello", "hello"],
    ["hello @agent there", "hello there"],
    ["no tag", "no tag"],
  ])("stripAgentMention(%j)", (content, expected) => {
    expect(stripAgentMention(content)).toBe(expected);
  });

  it("asks a watch run for the brief through the tool and as its last words", () => {
    const input = watchTaskInput({
      anchorText: "Signups grow weekly",
      requestId: "w-1",
      docTitle: "Super",
    });

    expect(input.question).toBe("Signups grow weekly");
    expect(input.description).toContain("“Signups grow weekly”");
    expect(input.description).toContain(
      'call doc-watch-brief-submit {"request_id": "w-1"',
    );
    expect(input.description).toContain(
      '{"claim", "confirms", "refutes", "evidence", "signals"}',
    );
  });
});
