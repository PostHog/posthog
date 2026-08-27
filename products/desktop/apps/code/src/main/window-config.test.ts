import { describe, expect, it } from "vitest";
import { getPlatformWindowConfig } from "./window-config";

describe("getPlatformWindowConfig", () => {
  it("passes the activation click through on macOS", () => {
    expect(getPlatformWindowConfig("darwin")).toEqual({
      acceptFirstMouse: true,
      titleBarStyle: "hidden",
      trafficLightPosition: { x: 14, y: 12 },
      titleBarOverlay: true,
    });
  });

  it("keeps the Windows title bar configuration", () => {
    expect(getPlatformWindowConfig("win32")).toEqual({
      titleBarStyle: "hidden",
      titleBarOverlay: {
        color: "#131316",
        symbolColor: "#ffffff",
        height: 36,
      },
    });
  });

  it("uses native window chrome on Linux", () => {
    expect(getPlatformWindowConfig("linux")).toEqual({});
  });
});
