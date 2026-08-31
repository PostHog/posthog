import { describe, expect, it } from "vitest";
import {
  type ObjectTagRef,
  objectWebPath,
  parseObjectTags,
} from "./objectTags";

function tags(text: string): ObjectTagRef[] {
  return parseObjectTags(text)
    .filter((segment) => segment.type === "tag")
    .map((segment) => segment.ref);
}

function texts(text: string): string[] {
  return parseObjectTags(text)
    .filter((segment) => segment.type === "text")
    .map((segment) => segment.value);
}

describe("parseObjectTags", () => {
  it("parses a self-closing tag into a reference", () => {
    expect(tags('<flag id="42"/>')).toEqual([
      { kind: "flag", id: "42", label: "42" },
    ]);
  });

  it("uses the body as the label for an open/close tag", () => {
    expect(tags('<insight id="9pQx3">checkout funnel</insight>')).toEqual([
      { kind: "insight", id: "9pQx3", label: "checkout funnel" },
    ]);
  });

  it("treats the body as the query for hogql references", () => {
    expect(
      tags('<hogql label="errors">SELECT count() FROM events</hogql>'),
    ).toEqual([
      { kind: "hogql", id: "SELECT count() FROM events", label: "errors" },
    ]);
  });

  it("resolves an alias to its registry kind", () => {
    expect(tags('<recording id="s1"/>')).toEqual([
      { kind: "replay", id: "s1", label: "s1" },
    ]);
  });

  it("keeps text around a tag literal", () => {
    expect(texts('see <flag id="42"/> here')).toEqual(["see ", " here"]);
  });

  it("leaves unknown tag names literal", () => {
    expect(tags("<span>hello</span>")).toEqual([]);
    expect(texts("<span>hello</span>")).toEqual(["<span>hello</span>"]);
  });

  it("hides a still-streaming tag until it completes", () => {
    expect(parseObjectTags('checkout <insight id="9pQx3">chec')).toEqual([
      { type: "text", value: "checkout " },
    ]);
  });

  it("drops a complete tag missing its id", () => {
    expect(parseObjectTags("<flag></flag>")).toEqual([]);
  });
});

describe("objectWebPath", () => {
  it("builds a page path for a known kind", () => {
    expect(objectWebPath("insight", "9pQx3")).toBe("/insights/9pQx3");
  });

  it("returns null for a flag cited by key", () => {
    expect(objectWebPath("flag", "my-flag-key")).toBeNull();
    expect(objectWebPath("flag", "42")).toBe("/feature_flags/42");
  });
});
