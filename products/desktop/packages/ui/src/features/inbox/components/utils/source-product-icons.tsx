import type { IconProps } from "@phosphor-icons/react";
import {
  BrainIcon,
  BugIcon,
  ChatsIcon,
  CompassIcon,
  FirstAidIcon,
  GitBranchIcon,
  GithubLogoIcon,
  KanbanIcon,
  LifebuoyIcon,
  LightbulbIcon,
  MagnifyingGlassIcon,
  MegaphoneIcon,
  ShieldIcon,
  StarIcon,
  TicketIcon,
  VideoIcon,
} from "@phosphor-icons/react";
import { JiraIcon } from "@posthog/ui/features/inbox/components/utils/JiraIcon";
import { PgAnalyzeIcon } from "@posthog/ui/features/inbox/components/utils/PgAnalyzeIcon";
import type { SourceProduct } from "@posthog/ui/features/inbox/stores/inboxSignalsFilterStore";
import type { ComponentType } from "react";

interface SourceProductMeta {
  Icon: ComponentType<IconProps>;
  color: string;
  label: string;
}

/**
 * Shared source product metadata used across inbox components. Keyed on
 * `SourceProduct` so typo'd lookups (e.g. `signal_scout`) fail to compile
 * rather than silently returning undefined at runtime.
 *
 * `Partial` because the backend may ship a new source product before the
 * renderer learns about it – callers must handle the `undefined` case.
 */
/**
 * Lookup helper that accepts the loosely-typed `source_products` strings
 * coming from the backend and returns metadata only when we recognize the
 * key. Use this instead of `SOURCE_PRODUCT_META[someString]` so an unknown
 * source product surfaces as `null` rather than a runtime error.
 */
export function getSourceProductMeta(
  value: string | null | undefined,
): SourceProductMeta | null {
  if (!value) return null;
  return SOURCE_PRODUCT_META[value as SourceProduct] ?? null;
}

/** True if at least one source product in `values` has known display metadata. */
export function hasKnownSourceProduct(
  values: string[] | null | undefined,
): boolean {
  return (values ?? []).some((value) => getSourceProductMeta(value) !== null);
}

export const SOURCE_PRODUCT_META: Partial<
  Record<SourceProduct, SourceProductMeta>
> = {
  session_replay: {
    Icon: VideoIcon,
    color: "var(--amber-9)",
    label: "Session replay",
  },
  error_tracking: {
    Icon: BugIcon,
    color: "var(--red-9)",
    label: "Error tracking",
  },
  llm_analytics: {
    Icon: BrainIcon,
    color: "var(--purple-9)",
    label: "AI observability",
  },
  github: {
    Icon: GithubLogoIcon,
    color: "var(--gray-11)",
    label: "GitHub",
  },
  linear: {
    Icon: KanbanIcon,
    color: "var(--blue-9)",
    label: "Linear",
  },
  jira: {
    Icon: JiraIcon,
    color: "var(--blue-11)",
    label: "Jira",
  },
  zendesk: {
    Icon: TicketIcon,
    color: "var(--green-9)",
    label: "Zendesk",
  },
  conversations: {
    Icon: LifebuoyIcon,
    color: "var(--cyan-9)",
    label: "Conversations",
  },
  pganalyze: {
    Icon: PgAnalyzeIcon,
    color: "var(--gray-12)",
    label: "pganalyze",
  },
  signals_scout: {
    Icon: CompassIcon,
    color: "var(--iris-9)",
    label: "Scout",
  },
  health_checks: {
    Icon: FirstAidIcon,
    color: "var(--crimson-9)",
    label: "Health checks",
  },
  // Warehouse-backed inbox sources
  freshdesk: {
    Icon: LifebuoyIcon,
    color: "var(--green-9)",
    label: "Freshdesk",
  },
  freshservice: {
    Icon: LifebuoyIcon,
    color: "var(--teal-9)",
    label: "Freshservice",
  },
  front: { Icon: ChatsIcon, color: "var(--blue-9)", label: "Front" },
  gorgias: { Icon: LifebuoyIcon, color: "var(--purple-9)", label: "Gorgias" },
  kustomer: { Icon: ChatsIcon, color: "var(--indigo-9)", label: "Kustomer" },
  dixa: { Icon: ChatsIcon, color: "var(--cyan-9)", label: "Dixa" },
  plain: { Icon: ChatsIcon, color: "var(--gray-11)", label: "Plain" },
  gitlab: { Icon: GitBranchIcon, color: "var(--orange-9)", label: "GitLab" },
  gitea: { Icon: GitBranchIcon, color: "var(--green-9)", label: "Gitea" },
  shortcut: { Icon: KanbanIcon, color: "var(--purple-9)", label: "Shortcut" },
  sentry: { Icon: BugIcon, color: "var(--violet-9)", label: "Sentry" },
  rollbar: { Icon: BugIcon, color: "var(--crimson-9)", label: "Rollbar" },
  bugsnag: { Icon: BugIcon, color: "var(--pink-9)", label: "Bugsnag" },
  honeybadger: {
    Icon: BugIcon,
    color: "var(--amber-9)",
    label: "Honeybadger",
  },
  raygun: { Icon: BugIcon, color: "var(--red-9)", label: "Raygun" },
  snyk: { Icon: ShieldIcon, color: "var(--purple-9)", label: "Snyk" },
  sonarqube: { Icon: ShieldIcon, color: "var(--blue-9)", label: "SonarQube" },
  semgrep: { Icon: ShieldIcon, color: "var(--green-9)", label: "Semgrep" },
  rapid7_insightvm: {
    Icon: ShieldIcon,
    color: "var(--orange-9)",
    label: "Rapid7 InsightVM",
  },
  featurebase: {
    Icon: LightbulbIcon,
    color: "var(--blue-9)",
    label: "Featurebase",
  },
  frill: { Icon: LightbulbIcon, color: "var(--cyan-9)", label: "Frill" },
  aha: { Icon: LightbulbIcon, color: "var(--red-9)", label: "Aha" },
  uservoice: {
    Icon: MegaphoneIcon,
    color: "var(--orange-9)",
    label: "UserVoice",
  },
  productboard: {
    Icon: LightbulbIcon,
    color: "var(--indigo-9)",
    label: "Productboard",
  },
  canny: { Icon: MegaphoneIcon, color: "var(--blue-9)", label: "Canny" },
  asknicely: { Icon: StarIcon, color: "var(--green-9)", label: "AskNicely" },
  retently: { Icon: StarIcon, color: "var(--teal-9)", label: "Retently" },
  appfigures: { Icon: StarIcon, color: "var(--blue-9)", label: "Appfigures" },
  appfollow: { Icon: StarIcon, color: "var(--green-9)", label: "AppFollow" },
  judgeme_reviews: {
    Icon: StarIcon,
    color: "var(--amber-9)",
    label: "Judge.me",
  },
  intercom: { Icon: ChatsIcon, color: "var(--blue-9)", label: "Intercom" },
  hubspot: { Icon: LifebuoyIcon, color: "var(--orange-9)", label: "HubSpot" },
  google_search_console: {
    Icon: MagnifyingGlassIcon,
    color: "var(--sky-9)",
    label: "Google Search Console",
  },
};
