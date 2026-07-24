import { describe, expect, it } from "vitest";
import { usageLimitContent } from "./usageLimitContent";

describe("usageLimitContent", () => {
  it("offers a payment method for the model gate", () => {
    const content = usageLimitContent({
      cause: "model_gate",
      resetLabel: null,
      subscribed: false,
    });
    expect(content.title).toBe("Unlock premium models");
    expect(content.description).toContain("This model isn't");
    expect(content.actionLabel).toBe("Add payment method");
  });

  it.each([
    // Confirmed-free org: allocation used up, the fix is adding a card.
    [false, "Free usage used up", "Add payment method"],
    // Subscribed org: the fix is raising the spend limit.
    [true, "Organization usage limit reached", "Manage billing"],
    // Unknown subscription state must not read as free.
    [undefined, "Organization usage limit reached", "Manage billing"],
  ] as const)(
    "org_limit with subscribed=%s -> %s / %s",
    (subscribed, title, actionLabel) => {
      const content = usageLimitContent({
        cause: "org_limit",
        resetLabel: null,
        subscribed,
      });
      expect(content.title).toBe(title);
      expect(content.actionLabel).toBe(actionLabel);
    },
  );

  it("includes the reset hint in the free-tier copy when available", () => {
    const content = usageLimitContent({
      cause: "org_limit",
      resetLabel: "Resets in 3h",
      subscribed: false,
    });
    expect(content.title).toBe("Free usage used up");
    expect(content.description).toContain("Resets in 3h");
  });

  it("renders generic copy without a billing CTA when the cause is unknown", () => {
    const content = usageLimitContent({
      cause: null,
      resetLabel: "Resets in 2h",
      subscribed: true,
    });
    expect(content.title).toBe("Usage limit reached");
    expect(content.description).toContain("Resets in 2h");
    expect(content.actionLabel).toBeNull();
    expect(content.dismissLabel).toBe("Got it");
  });
});
