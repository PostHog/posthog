import { describe, expect, it } from "vitest";
import {
  DEFAULT_POST_LOGIN_ROUTE,
  resolvePostLoginTarget,
} from "./postLoginTarget";

describe("resolvePostLoginTarget", () => {
  it("resumes a local deep link", () => {
    expect(resolvePostLoginTarget("/task/abc")).toBe("/task/abc");
  });

  it.each([
    { label: "missing", next: undefined },
    { label: "a repeated param", next: ["/task/a", "/task/b"] },
    { label: "not a local path", next: "https://evil.example.com" },
    { label: "the auth screen itself", next: "/auth" },
    { label: "the project picker", next: "/select-project" },
  ])("falls back to the default tab when next is $label", ({ next }) => {
    expect(resolvePostLoginTarget(next)).toBe(DEFAULT_POST_LOGIN_ROUTE);
  });
});
