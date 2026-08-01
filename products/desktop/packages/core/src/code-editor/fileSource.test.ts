import { describe, expect, it } from "vitest";
import {
  collapseFileState,
  resolveMarkdownLink,
  selectFileSource,
} from "./fileSource";

describe("selectFileSource", () => {
  it("enables repo source inside repo for non-image local file", () => {
    expect(
      selectFileSource({
        isInsideRepo: true,
        isCloudRun: false,
        isImage: false,
      }),
    ).toEqual({
      cloudEnabled: false,
      repoEnabled: true,
      absoluteEnabled: false,
      imageEnabled: false,
    });
  });

  it("enables cloud source for cloud run", () => {
    const flags = selectFileSource({
      isInsideRepo: true,
      isCloudRun: true,
      isImage: false,
    });
    expect(flags.cloudEnabled).toBe(true);
    expect(flags.repoEnabled).toBe(false);
  });

  it("enables image source only when not cloud", () => {
    expect(
      selectFileSource({
        isInsideRepo: false,
        isCloudRun: false,
        isImage: true,
      }).imageEnabled,
    ).toBe(true);
    expect(
      selectFileSource({ isInsideRepo: false, isCloudRun: true, isImage: true })
        .imageEnabled,
    ).toBe(false);
  });
});

describe("collapseFileState", () => {
  it("uses cloud file when cloud run", () => {
    expect(
      collapseFileState({
        cloudFile: { content: "cloud", isLoading: false },
        localQuery: { content: "local", isLoading: true, error: new Error() },
        isCloudRun: true,
      }),
    ).toEqual({ content: "cloud", isLoading: false, error: null });
  });

  it("uses local query when not cloud run", () => {
    const err = new Error("boom");
    expect(
      collapseFileState({
        cloudFile: { content: "cloud", isLoading: true },
        localQuery: { content: "local", isLoading: false, error: err },
        isCloudRun: false,
      }),
    ).toEqual({ content: "local", isLoading: false, error: err });
  });
});

describe("resolveMarkdownLink", () => {
  it("classifies http links as external", () => {
    const link = resolveMarkdownLink("https://x.com", "docs/a.md", "/repo");
    expect(link.kind).toBe("external");
    expect(link.relativePath).toBeNull();
  });

  it("resolves relative link against file dir", () => {
    const link = resolveMarkdownLink("./b.md", "docs/a.md", "/repo");
    expect(link.kind).toBe("internal");
    expect(link.relativePath).toBe("docs/b.md");
    expect(link.absolutePath).toBe("/repo/docs/b.md");
  });

  it("resolves link at repo root when file has no dir", () => {
    const link = resolveMarkdownLink("b.md", "a.md", null);
    expect(link.relativePath).toBe("b.md");
    expect(link.absolutePath).toBeNull();
  });
});
