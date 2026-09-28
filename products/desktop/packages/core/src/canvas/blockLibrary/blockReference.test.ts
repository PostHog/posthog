import { describe, expect, it } from "vitest";
import {
  type BlockReferenceInput,
  blockReferencePrompt,
} from "./blockReference";

const FILE = "src/canvas.tsx";
const LITERAL = `export default function Canvas() {
  return (
    <div className="grid">
      <KpiCard channel="Email" goal={600} />
      <KpiCard channel="Referral" goal={800} onOpen={() => open(">")} />
      <KpiCard channel="Email" goal={600} />
      <h1>Channels</h1>
    </div>
  )
}
`;
const LIST = `export default function Canvas() {
  return <div>{CHANNELS.map((c) => <KpiCard key={c.channel} {...c} />)}</div>
}
`;

const rangeOf = (text: string, needle: string, from = 0) => {
  const start = text.indexOf(needle, from);
  return { file: FILE, start, end: start + needle.length };
};

const base: BlockReferenceInput = {
  label: "kpi card",
  source: null,
  blockId: null,
  props: {},
  visibleText: null,
  instance: null,
};

describe("blockReferencePrompt", () => {
  it.each<[string, string, Partial<BlockReferenceInput>, string]>([
    [
      "uses the block id when there is one",
      LITERAL,
      {
        blockId: "b-email",
        source: rangeOf(LITERAL, '<KpiCard channel="Email" goal={600} />'),
      },
      "Change only this kpi card with blockId b-email in src/canvas.tsx: ",
    ],
    [
      "quotes the opening tag and skips an arrow inside braces",
      LITERAL,
      {
        source: rangeOf(
          LITERAL,
          '<KpiCard channel="Referral" goal={800} onOpen={() => open(">")} />',
        ),
      },
      'Change only this kpi card `<KpiCard channel="Referral" goal={800} onOpen={() => open(">")} />` in src/canvas.tsx: ',
    ],
    [
      "numbers identical tags in source order",
      LITERAL,
      {
        source: rangeOf(
          LITERAL,
          '<KpiCard channel="Email" goal={600} />',
          LITERAL.indexOf("Referral"),
        ),
      },
      'Change only this kpi card `<KpiCard channel="Email" goal={600} />` in src/canvas.tsx (match 2 of 2 for this code in the file): ',
    ],
    [
      "names the page instance, props, and text for code that renders many times",
      LIST,
      {
        source: rangeOf(LIST, "<KpiCard key={c.channel} {...c} />"),
        instance: { index: 3, count: 6 },
        props: { blockId: "ignored", goal: 1500, title: "Organic Social" },
        visibleText: " Organic Social\n 812 / 1500 ",
      },
      'Change only this kpi card `<KpiCard key={c.channel} {...c} />` in src/canvas.tsx (number 3 of the 6 on the page that this code renders, props goal={1500} title="Organic Social", showing "Organic Social 812 / 1500"): ',
    ],
    [
      "adds the visible text when the tag has no attributes",
      LITERAL,
      {
        label: "heading",
        source: rangeOf(LITERAL, "<h1>Channels</h1>"),
        visibleText: "Channels",
      },
      'Change only this heading `<h1>` in src/canvas.tsx (showing "Channels"): ',
    ],
  ])("%s", (_name, file, input, expected) => {
    expect(blockReferencePrompt({ ...base, ...input }, { [FILE]: file })).toBe(
      expected,
    );
  });
});
