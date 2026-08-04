import { describe, expect, it } from "vitest";
import { resolveMacFileIconBinary } from "./electron-file-icon";

describe("resolveMacFileIconBinary", () => {
  it("resolves the packaged extractor outside the ASAR", () => {
    expect(
      resolveMacFileIconBinary(
        "/Applications/PostHog Code.app/Contents/Resources/app.asar",
        true,
        "/unused/node_modules/file-icon/index.js",
      ),
    ).toBe(
      "/Applications/PostHog Code.app/Contents/Resources/app.asar.unpacked/node_modules/file-icon/file-icon",
    );
  });
});
