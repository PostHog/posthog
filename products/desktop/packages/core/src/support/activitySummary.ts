import type {
  SupportActivityChange,
  SupportActivityEntry,
} from "@posthog/api-client/posthog-client";
import { formatAbsoluteDateTime } from "@posthog/shared";

const DATE_FIELDS = new Set(["snoozed_until", "sla_due_at"]);

const FIELD_LABELS: Record<string, string> = {
  status: "status",
  priority: "priority",
  assignee: "assignee",
  snoozed_until: "snooze",
  sla_due_at: "SLA deadline",
  tags: "tags",
};

export function activityActorLabel(entry: SupportActivityEntry): string {
  if (entry.user) {
    const name = [entry.user.first_name, entry.user.last_name]
      .map((part) => part?.trim())
      .filter(Boolean)
      .join(" ");
    return name || entry.user.email || "Unknown";
  }
  return entry.is_system ? "PostHog" : "Unknown";
}

export function summarizeActivity(entry: SupportActivityEntry): string {
  if (entry.activity === "created") {
    return "created the ticket";
  }

  const described = (entry.detail?.changes ?? [])
    .map(describeChange)
    .filter((part): part is string => part !== null);

  if (described.length === 0) {
    return entry.activity === "updated" ? "updated the ticket" : entry.activity;
  }
  return described.join(", ");
}

function describeChange(change: SupportActivityChange): string | null {
  const field = change.field;
  if (!field) {
    return null;
  }

  if (field === "tag" || field === "tags") {
    return describeTagChange(change);
  }

  const label = FIELD_LABELS[field] ?? field.replace(/_/g, " ");
  const after = formatValue(field, change.after);
  return after ? `set ${label} to ${after}` : `cleared ${label}`;
}

function describeTagChange(change: SupportActivityChange): string {
  const before = asStrings(change.before);
  const after = asStrings(change.after);
  const added = after.filter((tag) => !before.includes(tag));
  const removed = before.filter((tag) => !after.includes(tag));

  if (added.length && !removed.length) {
    return `added ${added.join(", ")}`;
  }
  if (removed.length && !added.length) {
    return `removed ${removed.join(", ")}`;
  }
  return "updated tags";
}

function formatValue(field: string, value: unknown): string | null {
  if (value === null || value === undefined || value === "") {
    return null;
  }
  if (DATE_FIELDS.has(field) && typeof value === "string") {
    const parsed = Date.parse(value);
    return Number.isNaN(parsed) ? value : formatAbsoluteDateTime(parsed);
  }
  if (typeof value === "object") {
    const record = value as Record<string, unknown>;
    const user = record.user as { email?: string } | undefined;
    const role = record.role as { name?: string } | undefined;
    return user?.email ?? role?.name ?? "someone else";
  }
  return String(value);
}

// Ticket tag changes arrive one tag at a time (`field: "tag"`, a bare string),
// while the shared tagged-item path sends the whole list. Normalize both.
function asStrings(value: unknown): string[] {
  if (typeof value === "string") {
    return [value];
  }
  return Array.isArray(value) ? value.filter((v) => typeof v === "string") : [];
}
