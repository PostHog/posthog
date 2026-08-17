import { describe, expect, it } from "vitest";
import { extractChartBlocks } from "./chart-blocks";

const BLOCK = JSON.stringify({
  kind: "bar",
  title: "DAU",
  labels: ["8/1", "8/2"],
  series: [{ name: "DAU", points: [4, 5] }],
});

describe("extractChartBlocks", () => {
  it("extracts a fenced chart and strips it from the prose", () => {
    const { text, charts } = extractChartBlocks(
      `Here you go.\n\n\`\`\`posthog-chart\n${BLOCK}\n\`\`\`\n\nWeekends dip.`,
    );
    expect(text).toBe("Here you go.\n\n\n\nWeekends dip.");
    expect(charts).toEqual([
      {
        kind: "bar",
        title: "DAU",
        labels: ["8/1", "8/2"],
        series: [{ name: "DAU", points: [4, 5] }],
      },
    ]);
  });

  it.each([
    ["malformed JSON", "```posthog-chart\n{not json\n```"],
    ["no drawable series", '```posthog-chart\n{"series":[]}\n```'],
    [
      "non-numeric points",
      '```posthog-chart\n{"series":[{"points":["a"]}]}\n```',
    ],
  ])("drops a block with %s instead of leaking it as prose", (_name, block) => {
    const { text, charts } = extractChartBlocks(`Before.\n\n${block}`);
    expect(charts).toEqual([]);
    expect(text).toBe("Before.");
  });

  it("hides a fence that is still streaming in", () => {
    const { text, charts } = extractChartBlocks(
      'Numbers below.\n\n```posthog-chart\n{"kind":"line","series":[{"po',
    );
    expect(text).toBe("Numbers below.");
    expect(charts).toEqual([]);
  });
});
