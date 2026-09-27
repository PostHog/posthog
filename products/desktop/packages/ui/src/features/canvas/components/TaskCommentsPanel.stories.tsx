import {
  ALL_SOURCES,
  CommentListHeader,
  CommentSourceFilter,
  type CommentStateFilter,
} from "@posthog/ui/features/canvas/components/CommentListHeader";
import { CommentThreadGroups } from "@posthog/ui/features/canvas/components/CommentThreadGroups";
import {
  type CommentEntry,
  type TaskCommentThread,
  threadSourceOptions,
} from "@posthog/ui/features/canvas/components/taskCommentThreads";
import { CommentComposer } from "@posthog/ui/features/sessions/components/CommentComposer";
import {
  CommentQuote,
  CommentThreadCard,
} from "@posthog/ui/features/sessions/components/CommentThreadCard";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";

const PEOPLE = {
  ana: {
    id: 1,
    uuid: "u-1",
    email: "ana@example.com",
    first_name: "Ana",
    last_name: "Ruiz",
  },
  ben: {
    id: 2,
    uuid: "u-2",
    email: "ben@example.com",
    first_name: "Ben",
    last_name: "Okafor",
  },
  chen: {
    id: 3,
    uuid: "u-3",
    email: "chen@example.com",
    first_name: "Chen",
    last_name: "Wei",
  },
  dana: {
    id: 4,
    uuid: "u-4",
    email: "dana@example.com",
    first_name: "Dana",
    last_name: "Kim",
  },
  eli: {
    id: 5,
    uuid: "u-5",
    email: "eli@example.com",
    first_name: "Eli",
    last_name: "Park",
  },
  you: {
    id: 6,
    uuid: "u-6",
    email: "you@example.com",
    first_name: "You",
    last_name: "",
  },
};
type Person = keyof typeof PEOPLE;

const SOURCES = {
  canvas: { key: "canvas", label: "Q3 retention review", kind: "canvas" },
  plan: { key: "plan", label: "onboarding-plan.md", kind: "file" },
  pr: { key: "pr", label: "#812 Fix signup redirect", kind: "pr" },
  task: { key: "task", label: "This task", kind: "task" },
} as const;
type SourceId = keyof typeof SOURCES;

function minutesAgo(minutes: number): string {
  return new Date(Date.now() - minutes * 60_000).toISOString();
}

let nextId = 0;
function entry(person: Person, minutes: number, body: string): CommentEntry {
  const user = PEOPLE[person];
  nextId += 1;
  return {
    id: `entry-${nextId}`,
    authorName: [user.first_name, user.last_name].filter(Boolean).join(" "),
    user,
    avatarUrl: null,
    createdAt: minutesAgo(minutes),
    body,
    format: "mentions",
  };
}

type DemoThread = TaskCommentThread & {
  quote?: string;
  githubOnly?: boolean;
};

function thread(
  id: string,
  source: SourceId,
  entries: CommentEntry[],
  extra: Partial<DemoThread> = {},
): DemoThread {
  const { key, label, kind } = SOURCES[source];
  return {
    id,
    sourceKey: key,
    sourceLabel: label,
    sourceKind: kind,
    entries,
    resolved: false,
    startedAt: entries[0]?.createdAt ?? minutesAgo(0),
    origin: { kind: "pr-conversation", prUrl: "", url: null },
    ...extra,
  };
}

function demoThreads(): DemoThread[] {
  return [
    thread("t6", "task", [
      entry(
        "ben",
        20,
        "Can someone check the final numbers before we share this?",
      ),
    ]),
    thread(
      "t1",
      "canvas",
      [
        entry(
          "ana",
          120,
          "Is this drop real, or is it the new cohort definition? We changed it on the 14th.",
        ),
        entry(
          "ben",
          60,
          "It is the definition. I will add an annotation to the chart.",
        ),
        entry("ana", 45, "Thanks! Can you also put a note in the summary?"),
      ],
      { quote: "Week 4 retention dropped to 31%" },
    ),
    thread(
      "t2",
      "canvas",
      [
        entry(
          "chen",
          180,
          "Can we show this as a bar chart? The table is hard to scan.",
        ),
      ],
      { quote: "Top 5 features by usage" },
    ),
    thread(
      "t3",
      "plan",
      [
        entry(
          "dana",
          300,
          "Should this be day 1? Most drop-off happens in the first 24 hours.",
        ),
        entry("eli", 240, "Good point. Day 1 it is."),
        entry("dana", 238, "Updated the plan."),
        entry("ben", 180, "Let's check this again after one week of data."),
        entry("chen", 120, "+1, I will set a reminder."),
      ],
      { quote: "Send the welcome email on day 2" },
    ),
    thread(
      "t4",
      "plan",
      [
        entry(
          "eli",
          1440,
          "This section repeats the pricing page. Link to it instead?",
        ),
      ],
      { quote: "Pricing table" },
    ),
    thread(
      "t5",
      "pr",
      [
        {
          id: "gh-1",
          authorName: "code-reviewer",
          user: null,
          avatarUrl: null,
          createdAt: minutesAgo(360),
          body: "The `next` param is not validated here, so an open redirect is possible.",
          format: "markdown",
        },
      ],
      { githubOnly: true },
    ),
    thread(
      "t7",
      "canvas",
      [
        entry("dana", 2880, "Typo in the title."),
        entry("chen", 2870, "Fixed."),
      ],
      { resolved: true, quote: "Retnetion by plan" },
    ),
    thread("t8", "plan", [entry("ana", 4320, "Add an owner for each step?")], {
      resolved: true,
    }),
  ];
}

function TaskCommentsPanelDemo({ grouped }: { grouped: boolean }) {
  const [threads, setThreads] = useState(() =>
    grouped
      ? demoThreads()
      : demoThreads().filter((t) => t.sourceKey === "canvas"),
  );
  const [stateFilter, setStateFilter] = useState<CommentStateFilter>("open");
  const [sourceFilter, setSourceFilter] = useState(ALL_SOURCES);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  const inSource = (t: DemoThread) =>
    sourceFilter === ALL_SOURCES || t.sourceKey === sourceFilter;
  const scoped = threads.filter(inSource);
  const openCount = scoped.filter((t) => !t.resolved).length;
  const visible = scoped.filter(
    (t) => t.resolved === (stateFilter === "resolved"),
  );
  const sourceOptions = threadSourceOptions(
    threads.filter((t) => t.resolved === (stateFilter === "resolved")),
  );

  const update = (id: string, change: (t: DemoThread) => DemoThread) =>
    setThreads((current) => current.map((t) => (t.id === id ? change(t) : t)));

  return (
    <div className="flex h-[720px] w-[360px] flex-col overflow-hidden rounded-lg border border-border bg-background">
      <CommentListHeader
        stateFilter={stateFilter}
        openCount={openCount}
        resolvedCount={scoped.length - openCount}
        onStateFilterChange={setStateFilter}
        sourceFilter={
          grouped && (
            <CommentSourceFilter
              value={sourceFilter}
              valueLabel={
                sourceOptions.find((o) => o.key === sourceFilter)?.label ??
                "All sources"
              }
              options={sourceOptions}
              onChange={setSourceFilter}
            />
          )
        }
      />
      <div className="min-h-0 flex-1 overflow-y-auto">
        <CommentThreadGroups
          threads={visible}
          grouped={grouped}
          renderThread={(t) => {
            const demo = t as DemoThread;
            return (
              <CommentThreadCard
                key={demo.id}
                threadId={demo.id}
                entries={demo.entries}
                selected={demo.id === selectedId}
                pulsing={false}
                resolved={demo.resolved}
                members={[]}
                busy={false}
                source={demo.quote && <CommentQuote quote={demo.quote} />}
                resolution={demo.id === "t4" ? "orphaned" : undefined}
                canReply={!demo.githubOnly}
                canResolve={!demo.githubOnly}
                viewHref={demo.githubOnly ? "https://github.com" : undefined}
                onSelect={() => setSelectedId(demo.id)}
                onReply={(content) =>
                  update(demo.id, (current) => ({
                    ...current,
                    entries: [...current.entries, entry("you", 0, content)],
                  }))
                }
                onResolve={(resolved) =>
                  update(demo.id, (current) => ({ ...current, resolved }))
                }
              />
            );
          }}
        />
      </div>
      <footer className="shrink-0 border-border border-t bg-background p-2">
        <CommentComposer
          value={draft}
          onValueChange={setDraft}
          onSubmit={(content) => {
            const id = `new-${Date.now()}`;
            setThreads((current) => [
              thread(id, grouped ? "task" : "canvas", [
                entry("you", 0, content),
              ]),
              ...current,
            ]);
            setDraft("");
            setStateFilter("open");
            setSelectedId(id);
          }}
          members={[]}
          placeholder={`Comment on this ${grouped ? "task" : "canvas"}…`}
          rows={1}
          compact
        />
      </footer>
    </div>
  );
}

const meta = {
  title: "Canvas/TaskCommentsPanel",
  component: TaskCommentsPanelDemo,
  parameters: { layout: "centered" },
  args: { grouped: true },
} satisfies Meta<typeof TaskCommentsPanelDemo>;

export default meta;
type Story = StoryObj<typeof meta>;

export const GroupedBySource: Story = {};
export const SingleCanvas: Story = { args: { grouped: false } };
