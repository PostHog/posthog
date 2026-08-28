import { describe, expect, it } from "vitest";
import {
  summarizeCreatorSelection,
  summarizeSpaceSelection,
} from "./canvasFilterSelection";

const OPTIONS = [
  { value: null, label: "Anyone" },
  { value: "me", label: "Me" },
  { value: "ada", label: "Ada Lovelace" },
  { value: "grace", label: "Grace Hopper" },
];

describe("canvasFilterSelection", () => {
  it.each([
    { values: [], expected: "Anyone" },
    { values: ["me"], expected: "Me" },
    { values: ["me", "ada"], expected: "Me + 1 user" },
    { values: ["me", "ada", "grace"], expected: "Me + 2 users" },
    { values: ["ada", "grace"], expected: "2 users" },
  ])("summarizes creator selection as $expected", ({ values, expected }) => {
    expect(summarizeCreatorSelection(OPTIONS, values)).toBe(expected);
  });

  it.each([
    { values: [], expected: "Every space" },
    { values: ["ada"], expected: "Ada Lovelace" },
    { values: ["ada", "grace"], expected: "2 spaces" },
  ])("summarizes space selection as $expected", ({ values, expected }) => {
    expect(summarizeSpaceSelection(OPTIONS, values)).toBe(expected);
  });
});
