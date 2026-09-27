import { describe, expect, it } from "vitest";
import type { SitePolicy } from "./schemas";
import { SitePolicyStore } from "./site-policy";

function store(initial: Record<string, SitePolicy> = {}) {
  let sites = initial;
  return new SitePolicyStore(
    () => sites,
    (next) => {
      sites = next;
    },
  );
}

describe("SitePolicyStore", () => {
  it.each([
    ["a task sandbox", "https://abc-123.modal.host"],
    ["a local server", "http://localhost:3000"],
    ["a public site", "https://example.com"],
  ])("asks before the agent uses %s", (_name, origin) => {
    expect(store().access("task-1", origin)).toBe("ask");
  });

  it("keeps an approval inside the task that got it", () => {
    const policy = store();
    policy.approveForTask("task-1", "https://example.com");

    expect(policy.access("task-1", "https://example.com")).toBe("allowed");
    expect(policy.access("task-2", "https://example.com")).toBe("ask");

    policy.forgetTask("task-1");
    expect(policy.access("task-1", "https://example.com")).toBe("ask");
  });

  it("lets a block win over task approvals", () => {
    const policy = store();
    policy.approveForTask("task-1", "https://example.com");

    policy.set("https://example.com", "block");
    policy.set("http://localhost:3000", "block");

    expect(policy.access("task-1", "https://example.com")).toBe("blocked");
    expect(policy.access("task-1", "http://localhost:3000")).toBe("blocked");

    policy.set("https://example.com", null);
    expect(policy.access("task-1", "https://example.com")).toBe("ask");
  });

  it("asks again after the user removes a site they always allowed", () => {
    const policy = store();
    policy.approveForTask("task-1", "https://example.com");
    policy.set("https://example.com", "allow");

    policy.set("https://example.com", null);

    expect(policy.access("task-1", "https://example.com")).toBe("ask");
  });
});
