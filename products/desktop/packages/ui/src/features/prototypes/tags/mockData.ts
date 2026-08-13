/**
 * Static fixture data for the tags prototype. Everything here is invented —
 * people, repos, tasks, and timings exist only to make the prototype feel
 * inhabited. Nothing reads or writes real app state.
 */

export type PrototypeTaskStatus =
  | "needs_input"
  | "running"
  | "review"
  | "queued"
  | "done"
  | "failed";

export interface PrototypePerson {
  id: string;
  name: string;
  initials: string;
  /** Radix scale name used for the avatar fill, e.g. "blue" */
  hue: string;
  isViewer?: boolean;
}

export interface PrototypeTag {
  id: string;
  name: string;
  /** Radix scale name for the tag's dot and chips */
  hue: string;
  description: string;
  /** Repos an agent clones when a task starts under this tag */
  repos: string[];
  /** Context documents / prompts attached to new tasks under this tag */
  context: string[];
  /** Default agent preset for the tag */
  agentPreset: string;
  memberIds: string[];
  /** Subset of memberIds currently online (multiplayer presence) */
  onlineIds: string[];
}

export interface PrototypeActivityEntry {
  time: string;
  actor: string;
  text: string;
}

export interface PrototypeTask {
  id: string;
  title: string;
  tagIds: string[];
  status: PrototypeTaskStatus;
  /** One-line live description, e.g. "Writing migration tests…" */
  statusDetail: string;
  ownerId: string;
  participantIds: string[];
  repo: string;
  branch?: string;
  prUrl?: string;
  prState?: "open" | "merged" | "draft";
  updated: string;
  unread?: boolean;
  /** 0-100, only meaningful while running */
  progress?: number;
  activity: PrototypeActivityEntry[];
}

export const PEOPLE: PrototypePerson[] = [
  { id: "you", name: "You", initials: "YO", hue: "orange", isViewer: true },
  { id: "mara", name: "Mara Okafor", initials: "MO", hue: "blue" },
  { id: "dev", name: "Dev Chatterjee", initials: "DC", hue: "purple" },
  { id: "lena", name: "Lena Vogel", initials: "LV", hue: "green" },
  { id: "sam", name: "Sam Ruiz", initials: "SR", hue: "red" },
  { id: "kit", name: "Kit Andersen", initials: "KA", hue: "cyan" },
];

export const TAGS: PrototypeTag[] = [
  {
    id: "growth",
    name: "growth-experiments",
    hue: "green",
    description: "Signup funnel, activation and pricing-page experiments.",
    repos: ["acme/webapp", "acme/marketing-site"],
    context: ["Growth playbook.md", "Experiment naming rules"],
    agentPreset: "Claude · experiments preset",
    memberIds: ["you", "mara", "lena", "kit"],
    onlineIds: ["mara", "kit"],
  },
  {
    id: "billing",
    name: "billing",
    hue: "blue",
    description: "Invoicing, usage metering and the payments service.",
    repos: ["acme/billing-service"],
    context: ["Billing architecture notes", "Stripe test accounts"],
    agentPreset: "Claude · backend preset",
    memberIds: ["you", "dev", "sam"],
    onlineIds: ["dev"],
  },
  {
    id: "mobile",
    name: "mobile-replay",
    hue: "purple",
    description: "Session replay capture on iOS and Android.",
    repos: ["acme/sdk-ios", "acme/sdk-android"],
    context: ["Replay wire format spec"],
    agentPreset: "Claude · mobile preset",
    memberIds: ["lena", "sam"],
    onlineIds: [],
  },
  {
    id: "desktop",
    name: "desktop-app",
    hue: "yellow",
    description: "The Electron shell, sidebar and agent surfaces.",
    repos: ["acme/desktop"],
    context: ["Desktop UI conventions"],
    agentPreset: "Claude · frontend preset",
    memberIds: ["you", "mara", "dev", "lena", "kit"],
    onlineIds: ["mara", "dev", "lena"],
  },
  {
    id: "bugbash",
    name: "bug-bash",
    hue: "red",
    description: "Cross-team sweep of the top crash reports before release.",
    repos: ["acme/webapp", "acme/billing-service", "acme/desktop"],
    context: ["Release 2.4 crash triage"],
    agentPreset: "Claude · default",
    memberIds: ["you", "mara", "dev", "lena", "sam", "kit"],
    onlineIds: ["sam"],
  },
];

export const TASKS: PrototypeTask[] = [
  {
    id: "t1",
    title: "Fix double-charge when a plan changes mid-cycle",
    tagIds: ["billing", "bugbash"],
    status: "needs_input",
    statusDetail: "Agent is asking: proration strategy A or B?",
    ownerId: "you",
    participantIds: ["you", "dev"],
    repo: "acme/billing-service",
    branch: "fix/mid-cycle-proration",
    updated: "2m",
    unread: true,
    activity: [
      {
        time: "24m",
        actor: "agent",
        text: "Cloned acme/billing-service and reproduced the double charge in a test.",
      },
      {
        time: "9m",
        actor: "agent",
        text: "Found two viable proration strategies; drafted both.",
      },
      {
        time: "2m",
        actor: "agent",
        text: "Waiting for you: pick strategy A (credit note) or B (delta invoice).",
      },
    ],
  },
  {
    id: "t2",
    title: "Pricing page experiment: annual-first toggle",
    tagIds: ["growth"],
    status: "running",
    statusDetail: "Writing Playwright coverage for the toggle…",
    ownerId: "mara",
    participantIds: ["mara", "you"],
    repo: "acme/marketing-site",
    branch: "exp/annual-first",
    updated: "just now",
    progress: 62,
    activity: [
      {
        time: "41m",
        actor: "mara",
        text: "Started the task with the growth-experiments context.",
      },
      {
        time: "12m",
        actor: "agent",
        text: "Implemented the toggle behind the annual-first flag.",
      },
      {
        time: "1m",
        actor: "agent",
        text: "Writing Playwright coverage for the toggle.",
      },
    ],
  },
  {
    id: "t3",
    title: "Sidebar: collapse archived tasks into a footer row",
    tagIds: ["desktop"],
    status: "review",
    statusDetail: "PR #4821 open · 2 comments from Lena",
    ownerId: "you",
    participantIds: ["you", "lena"],
    repo: "acme/desktop",
    branch: "feat/archived-footer",
    prUrl: "#4821",
    prState: "open",
    updated: "18m",
    unread: true,
    activity: [
      { time: "3h", actor: "agent", text: "Opened PR #4821." },
      {
        time: "18m",
        actor: "lena",
        text: "Left 2 comments about keyboard focus.",
      },
    ],
  },
  {
    id: "t4",
    title: "Android replay: frames drop on foldables",
    tagIds: ["mobile", "bugbash"],
    status: "running",
    statusDetail: "Bisecting the capture loop regression…",
    ownerId: "lena",
    participantIds: ["lena", "sam"],
    repo: "acme/sdk-android",
    branch: "fix/foldable-frames",
    updated: "5m",
    progress: 30,
    activity: [
      {
        time: "1h",
        actor: "lena",
        text: "Started from crash report cluster #88.",
      },
      {
        time: "5m",
        actor: "agent",
        text: "Bisecting the capture loop regression.",
      },
    ],
  },
  {
    id: "t5",
    title: "Usage metering: backfill March gaps",
    tagIds: ["billing"],
    status: "running",
    statusDetail: "Dry-running the backfill against staging…",
    ownerId: "dev",
    participantIds: ["dev"],
    repo: "acme/billing-service",
    branch: "chore/march-backfill",
    updated: "just now",
    progress: 84,
    activity: [
      {
        time: "2h",
        actor: "dev",
        text: "Kicked off with the billing context pack.",
      },
      {
        time: "3m",
        actor: "agent",
        text: "Dry-running the backfill against staging.",
      },
    ],
  },
  {
    id: "t6",
    title: "Signup funnel: cut step 3 (company size)",
    tagIds: ["growth"],
    status: "review",
    statusDetail: "PR #1204 merged to staging, awaiting experiment start",
    ownerId: "kit",
    participantIds: ["kit", "mara"],
    repo: "acme/webapp",
    prUrl: "#1204",
    prState: "merged",
    updated: "1h",
    activity: [
      { time: "1d", actor: "kit", text: "Started the task." },
      {
        time: "1h",
        actor: "kit",
        text: "Merged to staging; experiment starts Monday.",
      },
    ],
  },
  {
    id: "t7",
    title: "Crash: NSInvalidArgumentException in replay encoder",
    tagIds: ["mobile", "bugbash"],
    status: "needs_input",
    statusDetail: "Agent needs a sample session file to reproduce",
    ownerId: "sam",
    participantIds: ["sam"],
    repo: "acme/sdk-ios",
    updated: "32m",
    activity: [
      {
        time: "50m",
        actor: "agent",
        text: "Could not reproduce from the stack trace alone.",
      },
      {
        time: "32m",
        actor: "agent",
        text: "Waiting for a sample session file.",
      },
    ],
  },
  {
    id: "t8",
    title: "Command palette: fuzzy match on tag names",
    tagIds: ["desktop"],
    status: "queued",
    statusDetail: "Queued behind 2 desktop tasks",
    ownerId: "you",
    participantIds: ["you"],
    repo: "acme/desktop",
    updated: "3h",
    activity: [{ time: "3h", actor: "you", text: "Queued the task." }],
  },
  {
    id: "t9",
    title: "Invoice PDFs render blank for JPY currencies",
    tagIds: ["billing", "bugbash"],
    status: "done",
    statusDetail: "PR #339 merged · shipped in 2.3.9",
    ownerId: "dev",
    participantIds: ["dev", "you"],
    repo: "acme/billing-service",
    prUrl: "#339",
    prState: "merged",
    updated: "1d",
    activity: [{ time: "1d", actor: "agent", text: "PR #339 merged." }],
  },
  {
    id: "t10",
    title: "Homepage hero: rotate customer logos experiment",
    tagIds: ["growth"],
    status: "done",
    statusDetail: "Experiment concluded: +2.1% CTR, shipping variant B",
    ownerId: "mara",
    participantIds: ["mara", "kit"],
    repo: "acme/marketing-site",
    prState: "merged",
    updated: "2d",
    activity: [
      { time: "2d", actor: "mara", text: "Concluded: shipping variant B." },
    ],
  },
  {
    id: "t11",
    title: "Windows: tray icon vanishes after sleep",
    tagIds: ["desktop", "bugbash"],
    status: "failed",
    statusDetail: "Agent run failed: could not reproduce on CI runner",
    ownerId: "kit",
    participantIds: ["kit"],
    repo: "acme/desktop",
    updated: "4h",
    activity: [
      {
        time: "5h",
        actor: "agent",
        text: "Attempted repro on the Windows CI runner.",
      },
      {
        time: "4h",
        actor: "agent",
        text: "Run failed: sleep/resume cannot be simulated on CI.",
      },
    ],
  },
  {
    id: "t12",
    title: "Meter events: dedupe retries at the edge",
    tagIds: ["billing"],
    status: "review",
    statusDetail: "PR #351 draft · benchmark results attached",
    ownerId: "you",
    participantIds: ["you", "dev", "sam"],
    repo: "acme/billing-service",
    prUrl: "#351",
    prState: "draft",
    updated: "42m",
    activity: [
      {
        time: "2h",
        actor: "agent",
        text: "Opened draft PR #351 with benchmarks.",
      },
      {
        time: "42m",
        actor: "sam",
        text: "Asked for a p99 latency comparison.",
      },
    ],
  },
];

export function personById(id: string): PrototypePerson {
  return PEOPLE.find((p) => p.id === id) ?? PEOPLE[0];
}

export const STATUS_META: Record<
  PrototypeTaskStatus,
  { label: string; tone: string; filled: boolean; pulse: boolean }
> = {
  needs_input: {
    label: "Needs you",
    tone: "var(--amber-9)",
    filled: true,
    pulse: true,
  },
  running: {
    label: "Running",
    tone: "var(--green-9)",
    filled: true,
    pulse: true,
  },
  review: {
    label: "In review",
    tone: "var(--blue-9)",
    filled: true,
    pulse: false,
  },
  queued: {
    label: "Queued",
    tone: "var(--gray-8)",
    filled: false,
    pulse: false,
  },
  done: { label: "Done", tone: "var(--gray-8)", filled: false, pulse: false },
  failed: { label: "Failed", tone: "var(--red-9)", filled: true, pulse: false },
};

export const STATUS_ORDER: PrototypeTaskStatus[] = [
  "needs_input",
  "running",
  "review",
  "queued",
  "failed",
  "done",
];

export const HOME_SECTION_LABELS: Record<PrototypeTaskStatus, string> = {
  needs_input: "Needs your attention",
  running: "Running now",
  review: "In review",
  queued: "Queued",
  failed: "Failed",
  done: "Recently done",
};
