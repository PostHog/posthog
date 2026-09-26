import { describe, expect, it } from "vitest";
import {
  sanitizeTaskPreviewGuestMessage,
  sanitizeTaskPreviewHostMessage,
} from "./task-preview-message";

const rect = { top: 1, left: 2, right: 3, bottom: 4, width: 1, height: 3 };
const element = {
  path: "/",
  selector: "#save",
  tag: "button",
  text: "Save",
  html: "<button>Save</button>",
  attributes: {},
};

describe("task preview messages", () => {
  it.each([
    {
      name: "a picked element",
      message: { type: "picked", element, rect },
      kept: true,
    },
    {
      name: "an element with oversized html",
      message: {
        type: "picked",
        element: { ...element, html: "x".repeat(2_001) },
        rect,
      },
      kept: false,
    },
    {
      name: "an element without a selector",
      message: { type: "picked", element: { ...element, selector: "" }, rect },
      kept: false,
    },
    {
      name: "a rect with a missing side",
      message: { type: "picked", element, rect: { ...rect, top: Number.NaN } },
      kept: false,
    },
    {
      name: "changed pins",
      message: { type: "pins-changed", ids: ["a", "b"] },
      kept: true,
    },
    {
      name: "changed pins with an empty id",
      message: { type: "pins-changed", ids: ["a", ""] },
      kept: false,
    },
    {
      name: "a tracked element rect",
      message: { type: "tracked-rect", rect },
      kept: true,
    },
    {
      name: "a tracked rect with a missing side",
      message: { type: "tracked-rect", rect: { ...rect, left: Number.NaN } },
      kept: false,
    },
    {
      name: "an unknown type",
      message: { type: "navigate", url: "https://x.test" },
      kept: false,
    },
  ])("keeps only valid guest messages: $name", ({ message, kept }) => {
    expect(sanitizeTaskPreviewGuestMessage(message) !== null).toBe(kept);
  });

  it("drops a pins message when one pin is malformed", () => {
    const pin = {
      id: "a",
      number: 1,
      path: "/",
      selector: "#a",
      text: "Save",
      active: false,
    };
    expect(
      sanitizeTaskPreviewHostMessage({ type: "pins", items: [pin] }),
    ).toEqual({ type: "pins", items: [pin] });
    expect(
      sanitizeTaskPreviewHostMessage({
        type: "pins",
        items: [pin, { ...pin, number: "2" }],
      }),
    ).toBeNull();
  });
});
