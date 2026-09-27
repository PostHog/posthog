import { describe, expect, it } from "vitest";
import { screenshotArea } from "./screenshot-area";

function rect(left: number, top: number, width: number, height: number) {
  return {
    left,
    top,
    width,
    height,
    right: left + width,
    bottom: top + height,
  };
}

describe("screenshotArea", () => {
  it.each([
    {
      name: "a small element in the middle gets room around it",
      element: rect(500, 400, 40, 20),
      expected: { x: 340, y: 300, width: 360, height: 220 },
    },
    {
      name: "an element at the top left corner stays inside the page",
      element: rect(0, 0, 100, 30),
      expected: { x: 0, y: 0, width: 360, height: 222 },
    },
    {
      name: "a wide element that ends near the left edge keeps a small area",
      element: rect(-10_000, 400, 10_020, 20),
      expected: { x: 0, y: 300, width: 360, height: 220 },
    },
    {
      name: "an element bigger than the page is cut to the page",
      element: rect(-50, -50, 2_000, 2_000),
      expected: { x: 0, y: 0, width: 1200, height: 800 },
    },
  ])("$name", ({ element, expected }) => {
    expect(screenshotArea(element, { width: 1200, height: 800 })).toEqual(
      expected,
    );
  });

  it.each([
    { name: "a hidden webview", element: rect(0, 0, 10, 10), width: 0 },
    {
      name: "an element right of the page",
      element: rect(1300, 400, 40, 20),
      width: 1200,
    },
    {
      name: "an element above the page",
      element: rect(500, -80, 40, 20),
      width: 1200,
    },
  ])("gives no area for $name", ({ element, width }) => {
    expect(
      screenshotArea(element, { width, height: width === 0 ? 0 : 800 }),
    ).toBeNull();
  });
});
