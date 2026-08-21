import type { GithubInstallRequestItem } from "@posthog/api-client/posthog-client";
import { describe, expect, it } from "vitest";
import {
  buildOrgOwnerMessage,
  hasPendingInstallRequest,
} from "./installRequests";

const request = (
  status: GithubInstallRequestItem["status"],
): GithubInstallRequestItem => ({
  id: status,
  github_login: "octocat",
  status,
  installation_id: null,
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
