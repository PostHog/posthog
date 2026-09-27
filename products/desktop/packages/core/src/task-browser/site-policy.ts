import type { SitePolicy } from "./schemas";

export function originOf(url: string): string | null {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" || parsed.protocol === "https:"
      ? parsed.origin
      : null;
  } catch {
    return null;
  }
}

export type SiteAccess = "allowed" | "blocked" | "ask";

export class SitePolicyStore {
  private readonly taskApprovals = new Map<string, Set<string>>();

  constructor(
    private readonly read: () => Record<string, SitePolicy>,
    private readonly write: (sites: Record<string, SitePolicy>) => void,
  ) {}

  access(taskId: string, origin: string): SiteAccess {
    const saved = this.read()[origin];
    if (saved === "block") return "blocked";
    if (saved === "allow") return "allowed";
    return this.taskApprovals.get(taskId)?.has(origin) ? "allowed" : "ask";
  }

  approveForTask(taskId: string, origin: string): void {
    const approvals = this.taskApprovals.get(taskId) ?? new Set<string>();
    approvals.add(origin);
    this.taskApprovals.set(taskId, approvals);
  }

  set(origin: string, policy: SitePolicy | null): void {
    const sites = { ...this.read() };
    if (policy) sites[origin] = policy;
    else delete sites[origin];
    this.write(sites);
    if (policy !== "allow") {
      for (const approvals of this.taskApprovals.values()) {
        approvals.delete(origin);
      }
    }
  }

  list(): Record<string, SitePolicy> {
    return { ...this.read() };
  }

  forgetTask(taskId: string): void {
    this.taskApprovals.delete(taskId);
  }
}
