import { describe, expect, it, vi } from "vitest";
import { describeElement, setupTaskPreviewPicker } from "./task-preview-picker";
import { uniqueSelector } from "./task-preview-selector";

describe("task preview picker", () => {
  it("never records the preview access token in the element path", () => {
    window.history.replaceState(
      null,
      "",
      "/settings?_modal_connect_token=secret-token&tab=billing#plan",
    );
    document.body.innerHTML = '<button id="save">Save   changes</button>';

    const element = describeElement(document.getElementById("save") as Element);

    expect(element.path).toBe("/settings?tab=billing#plan");
    expect(JSON.stringify(element)).not.toContain("secret-token");
    expect(element).toMatchObject({
      selector: "#save",
      tag: "button",
      text: "Save changes",
      attributes: { id: "save" },
    });
  });

  it.each([
    {
      name: "a unique id",
      html: '<div><span id="total">1</span></div>',
      pick: "#total",
      expected: "#total",
    },
    {
      name: "a data-attr",
      html: '<button data-attr="save">A</button><button data-attr="cancel">B</button>',
      pick: '[data-attr="cancel"]',
      expected: 'button[data-attr="cancel"]',
    },
    {
      name: "a position under an anchored parent",
      html: '<ul id="list"><li>A</li><li>B</li></ul><ul><li>C</li><li>D</li></ul>',
      pick: "#list li:nth-of-type(2)",
      expected: "#list > li:nth-of-type(2)",
    },
  ])(
    "builds a selector from $name that finds the same element",
    ({ html, pick, expected }) => {
      document.body.innerHTML = html;
      const element = document.querySelector(pick) as Element;

      const selector = uniqueSelector(element);

      expect(selector).toBe(expected);
      expect(document.querySelector(selector)).toBe(element);
    },
  );

  it("ignores a click the page script dispatches while picking", () => {
    document.body.innerHTML = '<button id="target">Go</button>';
    const send = vi.fn();
    const receive = setupTaskPreviewPicker(send);
    receive({ type: "pick", active: true });

    document
      .getElementById("target")
      ?.dispatchEvent(new MouseEvent("click", { bubbles: true }));

    expect(send).not.toHaveBeenCalledWith(
      expect.objectContaining({ type: "picked" }),
    );
    receive({ type: "pick", active: false });
  });
});
