import type { HomeRow } from "@posthog/core/home/homeRows";
import type {
  HomeNote,
  HomeStatus,
  HomeWorkKind,
} from "@posthog/core/home/schemas";
import type { UserBasic } from "@posthog/shared/domain-types";
import { HomePage } from "@posthog/ui/features/home/components/HomeView";
import { useHomeProjectsStore } from "@posthog/ui/features/home/homeProjectsStore";
import { useHomeViewStore } from "@posthog/ui/features/home/homeViewStore";
import type { Meta, StoryObj } from "@storybook/react-vite";

const ADA: UserBasic = {
  id: 1,
  uuid: "ada",
  email: "ada@example.com",
  first_name: "Ada",
  last_name: "Lovelace",
};

const GRACE: UserBasic = {
  id: 2,
  uuid: "grace",
  email: "grace@example.com",
  first_name: "Grace",
  last_name: "Hopper",
};

const SPACES = [
  { id: "space-ux", name: "ux-platform" },
  { id: "space-growth", name: "growth" },
  { id: "space-me", name: "me" },
];

const PROJECTS = [
  { id: "project-nav", spaceId: "space-ux", name: "Navigation rebuild" },
  { id: "project-signup", spaceId: "space-growth", name: "Signup funnel" },
];

const DAY = 86_400_000;
// Fixed clock so the relative timestamps in the rows don't move between runs.
const NOW = Date.parse("2026-08-12T12:00:00Z");

let sequence = 0;

/**
 * The notes the plan and todo rows stand for. A note row on the table is a view
 * of a record in the projects store, so the two have to carry the same id or
 * opening the row finds nothing.
 */
const NOTES: HomeNote[] = [];

function row(
  title: string,
  overrides: {
    kind?: HomeWorkKind;
    status?: HomeStatus;
    spaceId?: string;
    projectId?: string | null;
    assignee?: UserBasic | null;
    daysAgo?: number;
    pinned?: boolean;
    reference?: string | null;
  } = {},
): HomeRow {
  sequence += 1;
  const kind = overrides.kind ?? "session";
  const spaceId = overrides.spaceId ?? "space-ux";
  const project = PROJECTS.find((p) => p.id === overrides.projectId) ?? null;
  const updatedAt = NOW - (overrides.daysAgo ?? 0) * DAY;
  if ((kind === "plan" || kind === "todo") && project) {
    NOTES.push({
      id: String(sequence),
      projectId: project.id,
      kind,
      title,
      body:
        kind === "plan"
          ? "## Approach\n\nOne pass over the tree, then the keyboard paths."
          : "",
      status: overrides.status ?? "todo",
      assignee: overrides.assignee === undefined ? ADA : overrides.assignee,
      createdAt: updatedAt - DAY,
      updatedAt,
    });
  }
  return {
    key: `${kind}:${sequence}`,
    id: String(sequence),
    kind,
    title,
    status: overrides.status ?? "todo",
    reference:
      overrides.reference ?? (kind === "session" ? `#${100 + sequence}` : null),
    spaceId,
    spaceName: SPACES.find((s) => s.id === spaceId)?.name ?? "unknown",
    projectId: project?.id ?? null,
    projectName: project?.name ?? null,
    assignee: overrides.assignee === undefined ? ADA : overrides.assignee,
    createdAt: updatedAt - DAY,
    updatedAt,
    pinned: overrides.pinned ?? false,
    environment: kind === "session" ? "cloud" : null,
    source: null,
    task: null,
  };
}

const ROWS: HomeRow[] = [
  row("Rebuild the space switcher", {
    status: "in_progress",
    projectId: "project-nav",
    pinned: true,
  }),
  row("Sidebar drops focus when a space collapses", {
    status: "failed",
    projectId: "project-nav",
    assignee: GRACE,
    daysAgo: 1,
  }),
  row("Navigation rebuild plan", {
    kind: "plan",
    status: "in_progress",
    projectId: "project-nav",
    daysAgo: 2,
  }),
  row("Audit every keyboard path through the tree", {
    kind: "todo",
    status: "todo",
    projectId: "project-nav",
    assignee: GRACE,
    daysAgo: 2,
  }),
  row("Signup funnel by referrer", {
    kind: "canvas",
    status: "done",
    spaceId: "space-growth",
    projectId: "project-signup",
    daysAgo: 3,
  }),
  row("Trim the onboarding checklist", {
    status: "in_progress",
    spaceId: "space-growth",
    projectId: "project-signup",
    assignee: GRACE,
    daysAgo: 4,
  }),
  row("Add a retry to the invite email job", {
    status: "done",
    spaceId: "space-growth",
    daysAgo: 5,
  }),
  row("Scratch: compare two caching strategies", {
    status: "backlog",
    spaceId: "space-me",
    assignee: null,
    daysAgo: 9,
  }),
  row("Drop the legacy exporter", {
    status: "canceled",
    spaceId: "space-me",
    daysAgo: 21,
  }),
];

/**
 * Seeds the local projects registry and resets the view store, so each story
 * renders the same table no matter what the last one left behind.
 */
function seedStores({
  groupBy = "status" as const,
}: {
  groupBy?: "status" | "project" | "space";
} = {}) {
  useHomeProjectsStore.setState({
    projects: Object.fromEntries(
      PROJECTS.map((project) => [
        project.id,
        {
          ...project,
          status: "in_progress" as const,
          lead: ADA,
          createdAt: NOW,
          updatedAt: NOW,
        },
      ]),
    ),
    notes: Object.fromEntries(NOTES.map((note) => [note.id, note])),
    filing: {},
  });
  useHomeViewStore.setState({
    query: "",
    filters: {
      statuses: [],
      kinds: [],
      spaceIds: [],
      projectIds: [],
      assigneeUuids: [],
    },
    groupBy,
    sort: "recent",
    collapsedGroups: {},
  });
}

const meta = {
  title: "Home/HomePage",
  component: HomePage,
  parameters: { layout: "fullscreen" },
  args: {
    spaces: SPACES,
    rows: ROWS,
    isLoading: false,
    currentUser: ADA,
  },
  decorators: [
    (Story) => (
      <div className="h-screen">
        <Story />
      </div>
    ),
  ],
} satisfies Meta<typeof HomePage>;

export default meta;

type Story = StoryObj<typeof meta>;

export const GroupedByStatus: Story = {
  beforeEach: () => seedStores(),
};

export const GroupedByProject: Story = {
  beforeEach: () => seedStores({ groupBy: "project" }),
};

export const GroupedBySpace: Story = {
  beforeEach: () => seedStores({ groupBy: "space" }),
};

export const Loading: Story = {
  args: { isLoading: true },
  beforeEach: () => seedStores(),
};

export const NoPinnedSpaces: Story = {
  args: { spaces: [], rows: [] },
  beforeEach: () => seedStores(),
};

export const NoWorkYet: Story = {
  args: { rows: [] },
  beforeEach: () => seedStores(),
};
