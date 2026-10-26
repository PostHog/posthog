import { describe, expect, it } from "vitest";
import { selectProduct } from "./select-product";

describe("selectProduct", () => {
  it.each([
    ["slack", {}, "slack"],
    ["signal_report", {}, "signal_report"],
    ["workflow", { slack_reply_context: true }, "slack"],
    ["desktop", { slack_thread_url: "https://example.com/t" }, "slack"],
    ["desktop", { slack_reply_context: false }, undefined],
    [undefined, {}, undefined],
  ] as const)(
    "selects the product for origin %s with %o",
    (originProduct, launchOptions, expected) => {
      const product = selectProduct({
        taskId: "task-1",
        runId: "run-1",
        originProduct,
        launchOptions,
      });

      expect(product?.id).toBe(expected);
    },
  );
});
