import { describe, expect, it } from "vitest";
import { buildExitPlanModePermissionOptions } from "./permission-options";

describe("buildExitPlanModePermissionOptions", () => {
  it("does not relabel any option when no previous mode is provided", () => {
    const options = buildExitPlanModePermissionOptions();
    for (const opt of options) {
      expect(opt.name).not.toMatch(/^Yes, continue/);
    }
    expect(options[options.length - 1].optionId).toBe("reject_with_feedback");
  });

  it.each([
    {
      previousMode: "default",
      expectedName: "Yes, continue manually approving edits",
    },
    {
      previousMode: "auto",
      expectedName: 'Yes, continue in "auto" mode',
    },
    {
      previousMode: "acceptEdits",
      expectedName: "Yes, continue auto-accepting edits",
    },
  ])(
    "promotes the $previousMode mode to the first position with a continue label",
    ({ previousMode, expectedName }) => {
      const options = buildExitPlanModePermissionOptions(previousMode);
      expect(options[0]).toMatchObject({
        optionId: previousMode,
        name: expectedName,
      });
      expect(options[options.length - 1].optionId).toBe("reject_with_feedback");
    },
  );

  it("ignores an unknown previous mode", () => {
    const options = buildExitPlanModePermissionOptions("plan");
    expect(options[0].name).toMatch(/^Yes, /);
    expect(options[0].name).not.toMatch(/^Yes, continue/);
    expect(options[options.length - 1].optionId).toBe("reject_with_feedback");
  });

  it("always keeps the reject option last", () => {
    for (const previousMode of ["auto", "acceptEdits", "default", undefined]) {
      const options = buildExitPlanModePermissionOptions(previousMode);
      expect(options[options.length - 1].optionId).toBe("reject_with_feedback");
    }
  });
});
