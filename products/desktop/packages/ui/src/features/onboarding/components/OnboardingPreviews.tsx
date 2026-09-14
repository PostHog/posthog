import {
  ArrowUpIcon,
  CheckCircleIcon,
  ClockCounterClockwiseIcon,
  CloudIcon,
  GithubLogoIcon,
  LockSimpleIcon,
  PlusIcon,
  XIcon,
} from "@phosphor-icons/react";
import { Badge, Button } from "@posthog/quill";
import type { SignalReportPriority } from "@posthog/shared/types";
import { PriorityMonogram } from "@posthog/ui/features/inbox/components/PriorityMonogram";
import { DotsCircleSpinner } from "@posthog/ui/primitives/DotsCircleSpinner";
import type { ReactNode } from "react";

/** A static copy of an app surface. `inert` keeps its controls out of the tab order and the accessibility tree. */
function FauxScene({ children }: { children: ReactNode }) {
  return (
    <div
      inert
      className="flex min-w-0 flex-col gap-2 overflow-hidden rounded-(--radius-3) border border-border bg-gray-2 p-4 text-sm [background-image:radial-gradient(var(--gray-5)_1px,transparent_1px)] [background-size:12px_12px]"
    >
      {children}
    </div>
  );
}

function FauxComposerContext() {
  return (
    <div className="flex items-center gap-4 px-1 text-foreground">
      <span className="flex items-center gap-1.5">
        <LockSimpleIcon size={14} />
        personal
      </span>
      <span className="flex items-center gap-1.5">
        <CloudIcon size={14} />
        Cloud
      </span>
      <span className="flex items-center gap-1.5">
        <GithubLogoIcon size={14} />1 repository
      </span>
    </div>
  );
}

interface FauxComposerProps {
  placeholder: string;
  model?: { name: string; effort: string };
}

function FauxComposer({ placeholder, model }: FauxComposerProps) {
  return (
    <>
      <div className="flex items-center gap-2 rounded-(--radius-2) border border-border bg-card py-1.5 pr-1.5 pl-3 ring-(--gray-5) ring-3">
        <span className="min-w-0 flex-1 truncate text-muted-foreground">
          {placeholder}
        </span>
        <Badge className="shrink-0 gap-1">
          CONTEXT.md
          <XIcon size={10} />
        </Badge>
        <Button variant="primary" size="icon-sm" disabled aria-label="Send">
          <ArrowUpIcon />
        </Button>
      </div>
      <div className="flex items-center gap-1">
        <Button variant="link-muted" size="icon-sm" aria-label="Attach">
          <PlusIcon />
        </Button>
        {model && (
          <Button variant="link-muted" size="sm">
            <span className="text-foreground">{model.name}</span>
            {model.effort}
          </Button>
        )}
        <Button variant="link-muted" size="sm">
          Accept Edits
        </Button>
        <Button
          variant="link-muted"
          size="icon-sm"
          aria-label="Prompt history"
          className="ml-auto"
        >
          <ClockCounterClockwiseIcon />
        </Button>
      </div>
    </>
  );
}

export const composerPreview = (
  <FauxScene>
    <FauxComposerContext />
    <FauxComposer
      placeholder="What do you want to ship?"
      model={{ name: "Claude Opus 5", effort: "Medium" }}
    />
  </FauxScene>
);

interface FauxSlackMessage {
  key: string;
  author: string;
  avatarClassName: string;
  time: string;
  app?: boolean;
  body: ReactNode;
}

const slackMessages: FauxSlackMessage[] = [
  {
    key: "maya",
    author: "Maya",
    avatarClassName: "bg-(--blue-5)",
    time: "10:14",
    body: "signup page is throwing 500s again since the deploy, anyone around?",
  },
  {
    key: "jon",
    author: "Jon",
    avatarClassName: "bg-(--purple-5)",
    time: "10:16",
    body: (
      <>
        <span className="rounded-(--radius-1) bg-(--accent-3) px-1 text-(--accent-11)">
          @posthog
        </span>{" "}
        can you find the cause and open a PR?
      </>
    ),
  },
  {
    key: "posthog",
    author: "posthog",
    avatarClassName: "bg-(--accent-9)",
    time: "10:16",
    app: true,
    body: (
      <>
        On it. Started <span className="font-bold">Fix signup 500s</span> in
        team-synergy.{" "}
        <span className="text-muted-foreground">
          Following this thread for updates.
        </span>
      </>
    ),
  },
];

export const slackPreview = (
  <FauxScene>
    <div className="flex flex-col rounded-(--radius-2) border border-border bg-card">
      <div className="flex items-center gap-2 border-border border-b px-3 py-2">
        <span className="font-bold text-[13px]">#team-synergy</span>
        <span className="ml-auto text-muted-foreground text-xs">
          Thread · 3 replies
        </span>
      </div>
      <ul className="flex flex-col gap-3 p-3">
        {slackMessages.map((message) => (
          <li key={message.key} className="flex gap-2.5">
            <span
              className={`size-7 shrink-0 rounded-(--radius-1) ${message.avatarClassName}`}
            />
            <div className="flex min-w-0 flex-col gap-0.5 text-[13px]">
              <span className="flex items-center gap-1.5">
                <span className="font-bold">{message.author}</span>
                {message.app && <Badge>APP</Badge>}
                <span className="text-muted-foreground text-xs">
                  {message.time}
                </span>
              </span>
              <p>{message.body}</p>
            </div>
          </li>
        ))}
      </ul>
    </div>
  </FauxScene>
);

interface FauxListItem {
  key: string;
  lead: ReactNode;
  title: string;
  description: string;
  time: string;
  trailing?: ReactNode;
  selected?: boolean;
}

interface FauxListGroup {
  label: string;
  items: FauxListItem[];
}

function FauxList({ groups }: { groups: FauxListGroup[] }) {
  return (
    <div className="flex flex-col gap-1 rounded-(--radius-2) border border-border bg-card p-2">
      {groups.map((group) => (
        <div key={group.label} className="flex flex-col gap-0.5">
          <span className="px-2 pt-1.5 pb-1 font-medium text-[11px] text-gray-10 uppercase tracking-wide">
            {group.label}
          </span>
          {group.items.map((item) => (
            <div
              key={item.key}
              className={`flex items-start gap-2.5 rounded-(--radius-2) border px-2 py-2 ${item.selected ? "border-(--gray-6) bg-(--gray-3)" : "border-transparent"}`}
            >
              {item.lead}
              <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                <span className="truncate font-medium text-[13px] text-gray-12">
                  {item.title}
                </span>
                <span className="line-clamp-2 text-[12.5px] text-gray-11">
                  {item.description}
                </span>
                <span className="text-[12px] text-gray-10">{item.time}</span>
              </div>
              {item.trailing}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}

const unreadDot = (
  <span className="mt-1.5 size-2 shrink-0 rounded-full bg-(--blue-9)" />
);
const readDot = (
  <span className="mt-1.5 size-2 shrink-0 rounded-full border border-gray-9" />
);

function priority(value: SignalReportPriority) {
  return <PriorityMonogram priority={value} />;
}

export const selfDrivingPreview = (
  <FauxScene>
    <FauxList
      groups={[
        {
          label: "Yesterday",
          items: [
            {
              key: "signup",
              lead: priority("P1"),
              title: "Signup errors increased after the auth change",
              description:
                "New users on Safari get an error on the last signup step since the latest deploy.",
              time: "1d ago",
              trailing: readDot,
              selected: true,
            },
            {
              key: "invites",
              lead: priority("P3"),
              title: "Invite emails filtered as spam for some domains",
              description:
                "Invites sent to a few company domains bounce or never arrive.",
              time: "1d ago",
              trailing: unreadDot,
            },
          ],
        },
        {
          label: "This week",
          items: [
            {
              key: "feed",
              lead: priority("P2"),
              title: "Activity feed queries slow down on large projects",
              description:
                "The feed takes several seconds to load once a project passes a few thousand sessions.",
              time: "3d ago",
              trailing: unreadDot,
            },
          ],
        },
      ]}
    />
  </FauxScene>
);

const finishedRunIcon = (
  <CheckCircleIcon
    size={14}
    weight="fill"
    className="mt-0.5 shrink-0 text-(--green-9)"
  />
);

export const loopsPreview = (
  <FauxScene>
    <FauxList
      groups={[
        {
          label: "Weekly support digest · Mondays at 08:00",
          items: [
            {
              key: "running",
              lead: (
                <DotsCircleSpinner
                  size={14}
                  className="mt-0.5 text-(--accent-11)"
                />
              ),
              title: "Summarize this week's support tickets",
              description: "Reading 42 tickets from the last 7 days.",
              time: "Running now",
              selected: true,
            },
            {
              key: "sep-7",
              lead: finishedRunIcon,
              title: "Summarize this week's support tickets",
              description: "Report with 5 findings. Top issue: invite emails.",
              time: "7d ago",
            },
            {
              key: "aug-31",
              lead: finishedRunIcon,
              title: "Summarize this week's support tickets",
              description: "Report with 2 findings. No new issues.",
              time: "14d ago",
            },
          ],
        },
      ]}
    />
  </FauxScene>
);
