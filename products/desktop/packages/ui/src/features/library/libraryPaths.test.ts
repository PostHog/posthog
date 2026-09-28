import { describe, expect, it } from "vitest";
import { toLibraryHref, toWebAppLocation } from "./libraryPaths";

describe("libraryPaths", () => {
  it.each([
    ["/project/2/insights", "/library/project/2/insights"],
    ["project/2/insights?tab=saved", "/library/project/2/insights?tab=saved"],
  ])("maps the web app URL %s to %s", (webAppUrl, href) => {
    expect(toLibraryHref(webAppUrl)).toBe(href);
  });

  it.each([
    [
      { pathname: "/library/project/2/insights", search: "?a=1", hash: "#x" },
      { pathname: "/project/2/insights", search: "?a=1", hash: "#x" },
    ],
    [
      { pathname: "/library", search: "", hash: "" },
      { pathname: "/", search: "", hash: "" },
    ],
    [{ pathname: "/libraryx/project", search: "", hash: "" }, null],
    [{ pathname: "/spaces/abc", search: "", hash: "" }, null],
  ])("maps the shell location %o to %o", (shellLocation, expected) => {
    expect(toWebAppLocation(shellLocation)).toEqual(expected);
  });
});
