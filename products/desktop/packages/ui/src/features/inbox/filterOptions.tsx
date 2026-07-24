import {
  BrainIcon,
  BugIcon,
  CalendarPlus,
  Clock,
  CompassIcon,
  FirstAidIcon,
  LifebuoyIcon,
  ListNumbers,
  PlugIcon,
  TrendUp,
  VideoIcon,
} from "@phosphor-icons/react";
import { EXTERNAL_INBOX_SOURCES } from "@posthog/shared";
import type {
  AvailableSuggestedReviewer,
  SignalReportOrderingField,
  SignalReportPriority,
  SourceProduct,
} from "@posthog/shared/types";
import { getSourceProductMeta } from "@posthog/ui/features/inbox/components/utils/source-product-icons";
import type { ReactNode } from "react";

export type InboxSortField = Extract<
  SignalReportOrderingField,
  "priority" | "created_at" | "total_weight"
>;

export type InboxSortOption = {
  label: string;
  field: InboxSortField;
  direction: "asc" | "desc";
  icon: ReactNode;
};

export const INBOX_SORT_OPTIONS: InboxSortOption[] = [
  {
    label: "Priority first",
    field: "priority",
    direction: "asc",
    icon: <ListNumbers size={14} />,
  },
  {
    label: "Strongest evidence",
    field: "total_weight",
    direction: "desc",
    icon: <TrendUp size={14} />,
  },
  {
    label: "Newest first",
    field: "created_at",
    direction: "desc",
    icon: <CalendarPlus size={14} />,
  },
  {
    label: "Oldest first",
    field: "created_at",
    direction: "asc",
    icon: <Clock size={14} />,
  },
];

export const INBOX_PRIORITY_OPTIONS: {
  value: SignalReportPriority;
  accent: string;
}[] = [
  { value: "P0", accent: "var(--red-9)" },
  { value: "P1", accent: "var(--orange-9)" },
  { value: "P2", accent: "var(--amber-9)" },
  { value: "P3", accent: "var(--gray-9)" },
  { value: "P4", accent: "var(--gray-9)" },
];

export const INBOX_SOURCE_OPTIONS: {
  value: SourceProduct;
  label: string;
  icon: ReactNode;
}[] = [
  {
    value: "session_replay",
    label: "Session replay",
    icon: <VideoIcon size={14} />,
  },
  {
    value: "error_tracking",
    label: "Error tracking",
    icon: <BugIcon size={14} />,
  },
  {
    value: "llm_analytics",
    label: "AI observability",
    icon: <BrainIcon size={14} />,
  },
  {
    value: "conversations",
    label: "Conversations",
    icon: <LifebuoyIcon size={14} />,
  },
  { value: "signals_scout", label: "Scouts", icon: <CompassIcon size={14} /> },
  {
    value: "health_checks",
    label: "Health checks",
    icon: <FirstAidIcon size={14} />,
  },
  // Warehouse-backed sources, derived from the shared registry.
  ...EXTERNAL_INBOX_SOURCES.map((source) => {
    const meta = getSourceProductMeta(source.product);
    const Icon = meta?.Icon ?? PlugIcon;
    return {
      value: source.product,
      label: meta?.label ?? source.label,
      icon: <Icon size={14} />,
    };
  }),
];

export function inboxSortOptionKey(
  field: InboxSortField,
  direction: "asc" | "desc",
) {
  return `${field}:${direction}`;
}

export function inboxSourceFilterLabel(selected: SourceProduct[]): string {
  if (selected.length === 0) return "All sources";
  if (selected.length === 1) {
    return (
      INBOX_SOURCE_OPTIONS.find((option) => option.value === selected[0])
        ?.label ?? selected[0]
    );
  }
  return `${selected.length} sources`;
}

export function inboxPriorityFilterLabel(
  selected: SignalReportPriority[],
): string {
  if (selected.length === 0) return "All priorities";
  if (selected.length <= 2) return selected.join(", ");
  return `${selected.length} priorities`;
}

export interface CurrentSuggestedReviewerUser {
  uuid: string;
  email?: string | null;
  first_name?: string | null;
  last_name?: string | null;
}

export interface SuggestedReviewerFilterOption {
  uuid: string;
  name: string;
  email: string;
  github_login: string;
  isMe: boolean;
  showSeparatorBelow: boolean;
}

function normalizeString(value: string | null | undefined): string {
  return typeof value === "string" ? value.trim() : "";
}

function buildCurrentUserName(
  currentUser?: CurrentSuggestedReviewerUser | null,
): string {
  const firstName = normalizeString(currentUser?.first_name);
  const lastName = normalizeString(currentUser?.last_name);
  return [firstName, lastName].filter(Boolean).join(" ");
}

function sortReviewerOptionsByName(
  reviewers: SuggestedReviewerFilterOption[],
): SuggestedReviewerFilterOption[] {
  return [...reviewers].sort((a, b) => {
    const aName = normalizeString(a.name).toLowerCase();
    const bName = normalizeString(b.name).toLowerCase();
    const aEmail = normalizeString(a.email).toLowerCase();
    const bEmail = normalizeString(b.email).toLowerCase();

    return (
      aName.localeCompare(bName) ||
      aEmail.localeCompare(bEmail) ||
      a.uuid.localeCompare(b.uuid)
    );
  });
}

export function getSuggestedReviewerDisplayName(
  reviewer: Pick<SuggestedReviewerFilterOption, "name" | "email" | "isMe">,
): string {
  const baseLabel =
    normalizeString(reviewer.name) ||
    normalizeString(reviewer.email) ||
    "Unknown user";

  return reviewer.isMe ? `${baseLabel} (Me)` : baseLabel;
}

export function buildSuggestedReviewerFilterOptions(
  reviewers: AvailableSuggestedReviewer[],
  currentUser?: CurrentSuggestedReviewerUser | null,
): SuggestedReviewerFilterOption[] {
  const byUuid = new Map<string, SuggestedReviewerFilterOption>();

  for (const reviewer of reviewers) {
    const uuid = normalizeString(reviewer.uuid);
    if (!uuid || byUuid.has(uuid)) {
      continue;
    }

    byUuid.set(uuid, {
      uuid,
      name: normalizeString(reviewer.name),
      email: normalizeString(reviewer.email),
      github_login: normalizeString(reviewer.github_login),
      isMe: false,
      showSeparatorBelow: false,
    });
  }

  const currentUserUuid = normalizeString(currentUser?.uuid);
  if (currentUserUuid) {
    const existing = byUuid.get(currentUserUuid);
    byUuid.set(currentUserUuid, {
      uuid: currentUserUuid,
      name: buildCurrentUserName(currentUser) || existing?.name || "",
      email: normalizeString(currentUser?.email) || existing?.email || "",
      github_login: existing?.github_login || "",
      isMe: true,
      showSeparatorBelow: true,
    });
  }

  const options = Array.from(byUuid.values());
  const meOption = options.find((option) => option.isMe) ?? null;
  const otherOptions = sortReviewerOptionsByName(
    options.filter((option) => !option.isMe),
  );

  return meOption ? [meOption, ...otherOptions] : otherOptions;
}
