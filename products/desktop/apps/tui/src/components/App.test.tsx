import { renderToString } from "ink";
import { describe, expect, it } from "vitest";
import type { CloudRuns } from "../runs";
import type { WorkList } from "../work";
import { App } from "./App";

describe("App", () => {
  it("shows the Work sidebar", () => {
    const work = {
      listRecent: () => new Promise(() => {}),
    } as unknown as WorkList;
    const frame = renderToString(<App work={work} runs={{} as CloudRuns} />);
    expect(frame).toContain("Work");
  });
});
