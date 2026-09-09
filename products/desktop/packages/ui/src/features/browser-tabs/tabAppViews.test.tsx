import { EnvelopeSimple, FileTextIcon } from "@phosphor-icons/react";
import { isValidElement } from "react";
import { describe, expect, it } from "vitest";
import { resolveTabAppViewDisplay } from "./tabAppViews";

describe("resolveTabAppViewDisplay", () => {
  it.each([
    ["activity", EnvelopeSimple],
    ["report", FileTextIcon],
  ] as const)(
    "shows the report title on a %s tab, with its own icon",
    (appView, icon) => {
      const display = resolveTabAppViewDisplay(appView, {
        title: "Checkout errors increased",
      });

      expect(display.label).toBe("Checkout errors increased");
      expect(isValidElement(display.icon)).toBe(true);
      if (!isValidElement(display.icon)) return;
      expect(display.icon.type).toBe(icon);
    },
  );

  it.each([
    ["activity", null, "Activity"],
    ["report", null, "Report"],
    ["report", { title: "  " }, "Report"],
    ["inbox", { title: "Ignored report title" }, "Self-driving"],
  ] as const)("labels a %s tab with %o as %s", (appView, report, label) =>
    expect(resolveTabAppViewDisplay(appView, report).label).toBe(label),
  );
});
