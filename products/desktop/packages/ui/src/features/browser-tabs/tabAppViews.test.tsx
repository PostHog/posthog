import { EnvelopeSimple } from "@phosphor-icons/react";
import { isValidElement } from "react";
import { describe, expect, it } from "vitest";
import { resolveTabAppViewDisplay } from "./tabAppViews";

describe("resolveTabAppViewDisplay", () => {
  it("shows the report title and rail mail icon for an Activity report", () => {
    const display = resolveTabAppViewDisplay("activity", {
      title: "Checkout errors increased",
    });

    expect(display.label).toBe("Checkout errors increased");
    expect(isValidElement(display.icon)).toBe(true);
    if (!isValidElement(display.icon)) return;
    expect(display.icon.type).toBe(EnvelopeSimple);
  });

  it("keeps static labels for top-level destinations", () => {
    expect(resolveTabAppViewDisplay("activity", null).label).toBe("Activity");
    expect(
      resolveTabAppViewDisplay("inbox", { title: "Ignored report title" })
        .label,
    ).toBe("Self-driving");
  });
});
