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

const SOURCES = {
  canvas: ["Q3 retention review", "canvas"],
  plan: ["onboarding-plan.md", "file"],
  pr: ["#812 Fix signup redirect", "pr"],
  task: ["This task", "task"],
} as const;

type DemoThread = TaskCommentThread & { quote?: string; githubOnly?: boolean };

let nextId = 0;
function entry(name: string, minutes: number, body: string): CommentEntry {
  nextId += 1;
  const [first_name, last_name = ""] = name.split(" ");
  const email = `${first_name.toLowerCase()}@example.com`;
  return {
    id: `entry-${nextId}`,
    authorName: name,
    user: name.includes("-")
      ? null
      : { id: nextId, uuid: email, email, first_name, last_name },
    avatarUrl: null,
    createdAt: new Date(Date.now() - minutes * 60_000).toISOString(),
    body,
    format: name.includes("-") ? "markdown" : "mentions",
  };
}

function thread(
  id: string,
  source: keyof typeof SOURCES,
  entries: CommentEntry[],
  extra: Partial<DemoThread> = {},
): DemoThread {
  const [sourceLabel, sourceKind] = SOURCES[source];
  return {
    id,
    sourceKey: source,
    sourceLabel,
    sourceKind,
    entries,
    resolved: false,
    startedAt: entries[0].createdAt,
    origin: { kind: "pr-conversation", prUrl: "", url: null },
    ...extra,
  };
}

const demoThreads = (): DemoThread[] => [
  thread("t6", "task", [
    entry("Ben Okafor", 20, "Can someone check the final numbers?"),
  ]),
  thread(
    "t1",
    "canvas",
    [
      entry(
        "Ana Ruiz",
        120,
        "Is this drop real, or the new cohort definition?",
      ),
      entry(
        "Ben Okafor",
        60,
        "It is the definition. I will annotate the chart.",
      ),
      entry("Ana Ruiz", 45, "Thanks! Can you also note it in the summary?"),
    ],
    { quote: "Week 4 retention dropped to 31%" },
  ),
  thread(
    "t2",
    "canvas",
    [entry("Chen Wei", 180, "Can we show this as a bar chart?")],
    {
      quote: "Top 5 features by usage",
    },
  ),
  thread(
    "t3",
    "plan",
    [
      entry("Dana Kim", 300, "Should this be day 1? Most drop-off is early."),
      entry("Eli Park", 240, "Good point. Day 1 it is."),
      entry("Dana Kim", 238, "Updated the plan."),
      entry("Ben Okafor", 180, "Let's check again after one week of data."),
      entry("Chen Wei", 120, "+1, I will set a reminder."),
    ],
    { quote: "Send the welcome email on day 2" },
  ),
  thread(
    "t4",
    "plan",
    [entry("Eli Park", 1440, "This repeats the pricing page. Link it?")],
    {
      quote: "Pricing table",
    },
  ),
  thread(
    "t5",
    "pr",
    [entry("code-reviewer", 360, "The `next` param is not validated here.")],
    {
      githubOnly: true,
    },
  ),
  thread(
    "t7",
    "canvas",
    [
      entry("Dana Kim", 2880, "Typo in the title."),
      entry("Chen Wei", 2870, "Fixed."),
    ],
    {
      resolved: true,
      quote: "Retnetion by plan",
    },
  ),
  thread(
    "t8",
    "plan",
    [entry("Ana Ruiz", 4320, "Add an owner for each step?")],
    { resolved: true },
  ),
];

function TaskCommentsPanelDemo({ grouped }: { grouped: boolean }) {
  const [threads, setThreads] = useState(() =>
    demoThreads().filter((t) => grouped || t.sourceKey === "canvas"),
  );
  const [stateFilter, setStateFilter] = useState<CommentStateFilter>("open");
  const [sourceFilter, setSourceFilter] = useState(ALL_SOURCES);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  const inState = (t: DemoThread) =>
    t.resolved === (stateFilter === "resolved");
  const scoped = threads.filter(
    (t) => sourceFilter === ALL_SOURCES || t.sourceKey === sourceFilter,
  );
  const openCount = scoped.filter((t) => !t.resolved).length;
  const sourceOptions = threadSourceOptions(threads.filter(inState));
  const update = (id: string, change: Partial<DemoThread>) =>
    setThreads((current) =>
      current.map((t) => (t.id === id ? { ...t, ...change } : t)),
    );

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
          threads={scoped.filter(inState)}
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
                  update(demo.id, {
                    entries: [...demo.entries, entry("You", 0, content)],
                  })
                }
                onResolve={(resolved) => update(demo.id, { resolved })}
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
                entry("You", 0, content),
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
