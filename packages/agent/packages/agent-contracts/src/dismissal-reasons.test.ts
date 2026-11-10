import { describe, expect, it } from "vitest";
import {
  DISMISSAL_REASON_OPTIONS,
  dismissalReasonLabel,
  isDismissalReasonSnooze,
} from "./dismissal-reasons";

describe("dismissalReasonLabel", () => {
  it.each(DISMISSAL_REASON_OPTIONS)(
    "maps known reason $value to its label",
    ({ value, label }) => {
      expect(dismissalReasonLabel(value)).toBe(label);
    },
  );

  it("falls back to the raw code for an unrecognised reason", () => {
    expect(dismissalReasonLabel("some_brand_new_code")).toBe(
      "some_brand_new_code",
    );
  });
});

describe("isDismissalReasonSnooze", () => {
  it("is true for already_fixed and false for a permanent dismissal", () => {
    expect(isDismissalReasonSnooze("already_fixed")).toBe(true);
    expect(isDismissalReasonSnooze("wontfix_intentional")).toBe(false);
  });
});
