import { describe, expect, it } from "vitest";
import { isAbsolutePath, pathToFileUri } from "./path";

describe("isAbsolutePath", () => {
  it.each([
    ["/tmp/file.txt", true],
    ["C:\\Users\\me\\file.txt", true],
    ["C:/Users/me/file.txt", true],
    ["d:\\downloads\\file.txt", true],
    ["\\\\server\\share\\file.txt", true],
    ["//server/share/file.txt", true],
    ["relative/path.txt", false],
    ["./file.txt", false],
    ["../file.txt", false],
    ["file.txt", false],
    ["", false],
  ])("isAbsolutePath(%j) === %s", (input, expected) => {
    expect(isAbsolutePath(input)).toBe(expected);
  });
});

describe("pathToFileUri", () => {
  it("encodes a POSIX absolute path", () => {
    expect(pathToFileUri("/tmp/test.txt")).toBe("file:///tmp/test.txt");
  });

  it("percent-encodes POSIX path segments with spaces and reserved chars", () => {
    expect(pathToFileUri("/tmp/My Folder/a#b?.txt")).toBe(
      "file:///tmp/My%20Folder/a%23b%3F.txt",
    );
  });

  it("encodes a Windows drive path with single backslashes", () => {
    expect(pathToFileUri("C:\\tmp\\file.txt")).toBe("file:///C:/tmp/file.txt");
  });

  it("encodes a Windows drive path that already uses forward slashes", () => {
    expect(pathToFileUri("C:/tmp/file.txt")).toBe("file:///C:/tmp/file.txt");
  });

  it("uppercases the drive letter", () => {
    expect(pathToFileUri("c:\\tmp\\file.txt")).toBe("file:///C:/tmp/file.txt");
  });

  it("percent-encodes Windows drive path segments with special chars", () => {
    expect(pathToFileUri("C:\\tmp\\100%\\a#b?.txt")).toBe(
      "file:///C:/tmp/100%25/a%23b%3F.txt",
    );
  });

  it("encodes a UNC path with the host as the URI authority", () => {
    expect(pathToFileUri("\\\\server\\share\\My Folder\\file.txt")).toBe(
      "file://server/share/My%20Folder/file.txt",
    );
  });

  it("encodes a UNC path already normalized to forward slashes", () => {
    expect(pathToFileUri("//server/share/file.txt")).toBe(
      "file://server/share/file.txt",
    );
  });

  it("returns existing file:// URIs unchanged", () => {
    const uri = "file:///tmp/file.txt";
    expect(pathToFileUri(uri)).toBe(uri);
  });

  it("round-trips literal percent signs via re-encoding", () => {
    // Already-encoded segments are re-encoded so the original characters round-trip
    // through decodeURIComponent.
    expect(pathToFileUri("/tmp/100%25")).toBe("file:///tmp/100%2525");
  });
});
