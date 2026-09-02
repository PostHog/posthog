import { describe, expect, it } from "vitest";
import {
  type PanelDrag,
  resolvePanelDrag,
  resolvePanelGeometry,
  resolvePanelWidth,
} from "./rightPanelGeometry";

describe("resolvePanelWidth", () => {
  it.each<{
    name: string;
    stored: number;
    rowWidth: number;
    expected: number;
  }>([
    {
      name: "a dragged width is kept as it is",
      stored: 900,
      rowWidth: 1600,
      expected: 900,
    },
    {
      name: "a drag to the row's far edge stops short of covering it",
      stored: 1600,
      rowWidth: 1600,
      expected: 1550,
    },
    {
      name: "a width dragged out on a wider window still fits this row",
      stored: 2400,
      rowWidth: 1600,
      expected: 1550,
    },
    {
      name: "a width dragged in past the panel's floor is held at it",
      stored: 120,
      rowWidth: 1600,
      expected: 280,
    },
    {
      name: "a row with less room than the floor gives what it has",
      stored: 120,
      rowWidth: 200,
      expected: 150,
    },
  ])("$name", ({ stored, rowWidth, expected }) => {
    expect(resolvePanelWidth(stored, rowWidth)).toBe(expected);
  });
});

describe("resolvePanelDrag", () => {
  // A 1600px row: the panel's ceiling is 1550, its floor 280, and the drag
  // closes below 140 / reopens at 156.
  const rowWidth = 1600;

  it.each<{
    name: string;
    pointer: number;
    open: boolean;
    expanded: boolean;
    expected: PanelDrag;
  }>([
    {
      name: "dragging an open panel sets the width the pointer asks for",
      pointer: 700,
      open: true,
      expanded: false,
      expected: { action: "resize", width: 700 },
    },
    {
      name: "dragging an open panel past its floor closes it",
      pointer: 100,
      open: true,
      expanded: false,
      expected: { action: "close" },
    },
    {
      name: "dragging back out while still held brings it in again",
      pointer: 200,
      open: false,
      expanded: false,
      expected: { action: "reopen", width: 280 },
    },
    {
      name: "a closed panel between the two lines stays closed",
      pointer: 150,
      open: false,
      expanded: false,
      expected: { action: "hold" },
    },
    {
      name: "dragging an expanded panel in takes it off the full row",
      pointer: 900,
      open: true,
      expanded: true,
      expected: { action: "collapse", width: 900 },
    },
    {
      name: "dragging an expanded panel out asks for room it hasn't got",
      pointer: 1900,
      open: true,
      expanded: true,
      expected: { action: "hold" },
    },
    {
      name: "an expanded panel dragged past its floor collapses on the way",
      pointer: 100,
      open: true,
      expanded: true,
      expected: { action: "collapse", width: 280 },
    },
  ])("$name", ({ pointer, open, expanded, expected }) => {
    expect(resolvePanelDrag({ pointer, rowWidth, open, expanded })).toEqual(
      expected,
    );
  });
});

describe("resolvePanelGeometry", () => {
  // A 1600px row: the panel covers past 800 and is at full width from 1550.
  const rowWidth = 1600;

  it.each<{
    name: string;
    storedWidth: number;
    open?: boolean;
    expanded?: boolean;
    rowWidth?: number;
    covering: boolean;
    atFullWidth: boolean;
  }>([
    {
      name: "a narrow panel pushes the pane and covers nothing",
      storedWidth: 340,
      covering: false,
      atFullWidth: false,
    },
    {
      name: "a panel past the push share covers the pane",
      storedWidth: 900,
      covering: true,
      atFullWidth: false,
    },
    {
      name: "a panel dragged to the ceiling is at full width",
      storedWidth: 1550,
      covering: true,
      atFullWidth: true,
    },
    {
      name: "an expanded panel is covering and full however wide it was left",
      storedWidth: 340,
      expanded: true,
      covering: true,
      atFullWidth: true,
    },
    {
      name: "a closed panel sits nowhere",
      storedWidth: 1550,
      open: false,
      covering: false,
      atFullWidth: false,
    },
    {
      name: "an unmeasured row can't say where the panel sits",
      storedWidth: 1550,
      rowWidth: 0,
      covering: false,
      atFullWidth: false,
    },
  ])(
    "$name",
    ({
      storedWidth,
      open = true,
      expanded = false,
      covering,
      atFullWidth,
      ...rest
    }) => {
      expect(
        resolvePanelGeometry({
          storedWidth,
          rowWidth: rest.rowWidth ?? rowWidth,
          open,
          expanded,
        }),
      ).toMatchObject({ covering, atFullWidth });
    },
  );

  it("hands back the width that stops short of covering", () => {
    expect(
      resolvePanelGeometry({
        storedWidth: 900,
        rowWidth,
        open: true,
        expanded: false,
      }).uncoveredWidth,
    ).toBe(800);
  });
});
