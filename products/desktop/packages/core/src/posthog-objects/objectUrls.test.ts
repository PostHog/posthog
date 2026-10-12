import { describe, expect, it } from "vitest";
import { parsePostHogObjectUrl } from "./objectUrls";

const CONTEXT = { appUrl: "https://us.posthog.com", projectId: 2 };
const PROJECT = "https://us.posthog.com/project/2";
const HOGQL_NODE = encodeURIComponent(
  JSON.stringify({
    kind: "DataVisualizationNode",
    source: { kind: "HogQLQuery", query: "SELECT 1" },
  }),
);

describe("parsePostHogObjectUrl", () => {
  it.each([
    [`${PROJECT}/insights/9pQx3`, ["insight", "9pQx3"]],
    [`${PROJECT}/insights/9pQx3/edit?x=1`, ["insight", "9pQx3"]],
    [`${PROJECT}/i/9pQx3`, ["insight", "9pQx3"]],
    ["https://us.posthog.com/insights/9pQx3", ["insight", "9pQx3"]],
    ["https://app.posthog.com/project/2/insights/9pQx3", ["insight", "9pQx3"]],
    [
      `${PROJECT}/sql?open_query=SELECT%20count()%20FROM%20events`,
      ["hogql", "SELECT count() FROM events"],
    ],
    [`${PROJECT}/sql?open_query=SELECT+1`, ["hogql", "SELECT 1"]],
    [`${PROJECT}/sql?open_query=${HOGQL_NODE}`, ["hogql", "SELECT 1"]],
    [`${PROJECT}/insights/new#q=${HOGQL_NODE}`, ["hogql", "SELECT 1"]],
    [`${PROJECT}/replay/0190-s1?t=30`, ["replay", "0190-s1"]],
    [
      `${PROJECT}/replay/home?sessionRecordingId=0190-s1`,
      ["replay", "0190-s1"],
    ],
    [`${PROJECT}/feature_flags/42`, ["flag", "42"]],
    [`${PROJECT}/persons/a%20b`, ["person", "a b"]],
    [`${PROJECT}/feature_flags/my-key`, null],
    [`${PROJECT}/insights/new`, null],
    [
      `${PROJECT}/insights/new#q=${encodeURIComponent('{"kind":"TrendsQuery"}')}`,
      null,
    ],
    [`${PROJECT}/replay/home`, null],
    [`${PROJECT}/sql?open_query=`, null],
    [`${PROJECT}/settings/project`, null],
    ["https://us.posthog.com/project/3/insights/9pQx3", null],
    ["https://eu.posthog.com/project/2/insights/9pQx3", null],
    ["https://us.posthog.com.evil.example/project/2/insights/9pQx3", null],
    ["javascript:alert(1)", null],
    ["evidence:insight/9pQx3", null],
  ])("resolves %s", (url, expected) => {
    const ref = parsePostHogObjectUrl(url, CONTEXT);
    expect(ref ? [ref.kind, ref.id] : null).toEqual(expected);
  });

  it("keeps the exact page the link opens", () => {
    expect(
      parsePostHogObjectUrl(`${PROJECT}/replay/s1?t=30`, CONTEXT)?.href,
    ).toBe(`${PROJECT}/replay/s1?t=30`);
  });

  it("recognizes nothing without a signed-in project", () => {
    expect(parsePostHogObjectUrl(`${PROJECT}/insights/9pQx3`, null)).toBe(null);
  });
});
