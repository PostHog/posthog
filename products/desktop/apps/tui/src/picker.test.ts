import { stripTerminalSequences } from "@earendil-works/pi-tui";
import { describe, expect, it } from "vitest";
import {
  applyPickerKey,
  openPicker,
  type Picker,
  pickerKey,
  pickerRows,
  renderPicker,
} from "./picker";

const searched = (selected: string[], results: string[]): Picker => ({
  ...openPicker("Repositories", selected),
  results,
  loading: false,
});

const press = (picker: Picker, ...sequences: string[]): Picker =>
  sequences.reduce((current, sequence) => {
    const key = pickerKey(sequence);
    const next = key ? applyPickerKey(current, key) : current;
    if (typeof next === "string") throw new Error(`picker closed: ${next}`);
    return next;
  }, picker);

describe("picker", () => {
  it("keeps ticked items on top, with the cursor on an item as it moves", () => {
    const picker = press(
      searched(["posthog/posthog"], ["posthog/posthog", "posthog/posthog-js"]),
      "\u001b[B",
      " ",
    );
    expect(pickerRows(picker)).toEqual([
      "posthog/posthog",
      "posthog/posthog-js",
    ]);
    expect(picker.selected).toEqual(["posthog/posthog", "posthog/posthog-js"]);
    expect(picker.index).toBe(1);

    const unticked = press(picker, "\u001b[A", " ");
    expect(unticked.selected).toEqual(["posthog/posthog-js"]);
    expect(pickerRows(unticked)[unticked.index]).toBe("posthog/posthog");
  });

  it("types into the search and erases from it, keeping what is ticked", () => {
    const picker = press(searched(["a/b"], []), "j", "s", "\u007f");
    expect(picker.query).toBe("j");
    expect(picker.selected).toEqual(["a/b"]);
  });

  it.each([
    ["\r", "confirm"],
    ["\u001b", "dismiss"],
  ])("closes on %j with %s", (sequence, expected) => {
    const key = pickerKey(sequence);
    expect(key && applyPickerKey(searched([], ["a/b"]), key)).toBe(expected);
  });

  it("says why the list is empty", () => {
    const lines = (picker: Picker) =>
      stripTerminalSequences(renderPicker(picker, 60).join("\n"));
    expect(lines(openPicker("Repositories", []))).toContain("Searching…");
    expect(lines({ ...searched([], []), query: "zz" })).toContain(
      'Nothing matches "zz"',
    );
  });
});
