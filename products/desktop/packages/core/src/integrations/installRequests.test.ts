import type { GithubInstallRequestItem } from "@posthog/api-client/posthog-client";
import { describe, expect, it } from "vitest";
import {
  buildOrgOwnerMessage,
  hasPendingInstallRequest,
  unlinkedApprovedRequests,
} from "./installRequests";

const request = (
  status: GithubInstallRequestItem["status"],
  installation_id: string | null = null,
): GithubInstallRequestItem => ({
  id: installation_id ?? status,
  github_login: "octocat",
  status,
  installation_id,
  requested_at: "2026-08-18T00:00:00Z",
  resolved_at: null,
});

describe("hasPendingInstallRequest", () => {
  it.each([
    ["undefined", undefined, false],
    ["empty", [], false],
    ["only approved", [request("approved")], false],
    ["mixed", [request("approved"), request("pending")], true],
  ])("%s", (_name, requests, expected) => {
    expect(hasPendingInstallRequest(requests)).toBe(expected);
  });
});

describe("buildOrgOwnerMessage", () => {
  it("names the install page the owner should open", () => {
    expect(
      buildOrgOwnerMessage("https://github.com/apps/posthog/installations/new"),
    ).toContain("https://github.com/apps/posthog/installations/new");
  });
});

describe("unlinkedApprovedRequests", () => {
  it.each([
    ["undefined", undefined, [], []],
    ["only pending is never returned", [request("pending", "123")], [], []],
    [
      "approved and not yet linked stays",
      [request("approved", "123")],
      [],
      ["123"],
    ],
    [
      "approved but already linked drops out",
      [request("approved", "123")],
      ["123"],
      [],
    ],
    [
      "approved without an installation id stays",
      [request("approved", null)],
      ["123"],
      [null],
    ],
    [
      "one linked, one still unlinked",
      [request("approved", "123"), request("approved", "456")],
      ["123"],
      ["456"],
    ],
  ] as const)("%s", (_name, requests, linkedIds, expectedIds) => {
    expect(
      unlinkedApprovedRequests(requests, linkedIds).map(
        (r) => r.installation_id,
      ),
    ).toEqual(expectedIds);
  });
});
