import { describe, expect, it } from "vitest";
import {
  isTextEntryTarget,
  resolveReportCardClickIntent,
} from "./reportSelection";

const NO_MODIFIERS = { shiftKey: false, metaKey: false, ctrlKey: false };

describe("reportSelection", () => {
  describe("resolveReportCardClickIntent", () => {
    it.each([
      ["plain click with nothing selected opens", NO_MODIFIERS, false, "open"],
      ["plain click in selection mode toggles", NO_MODIFIERS, true, "toggle"],
      [
        "meta click toggles from empty",
        { ...NO_MODIFIERS, metaKey: true },
        false,
        "toggle",
      ],
      [
        "ctrl click toggles from empty",
        { ...NO_MODIFIERS, ctrlKey: true },
        false,
        "toggle",
      ],
      [
        "shift click ranges from empty",
        { ...NO_MODIFIERS, shiftKey: true },
        false,
        "range",
      ],
      [
        "shift wins over meta",
        { shiftKey: true, metaKey: true, ctrlKey: false },
        true,
        "range",
      ],
    ] as const)("%s", (_name, modifiers, hasSelection, expected) => {
      expect(resolveReportCardClickIntent(modifiers, hasSelection)).toBe(
        expected,
      );
    });
  });

  describe("isTextEntryTarget", () => {
    it("treats a text input as text entry, so Esc stays with the field", () => {
      const input = document.createElement("input");
      input.type = "search";
      expect(isTextEntryTarget(input)).toBe(true);
    });

    it.each(["checkbox", "button"])(
      "treats a %s input as a control",
      (type) => {
        const input = document.createElement("input");
        input.type = type;
        expect(isTextEntryTarget(input)).toBe(false);
      },
    );

    it("treats a card div as a control", () => {
      expect(isTextEntryTarget(document.createElement("div"))).toBe(false);
    });
  });
});
