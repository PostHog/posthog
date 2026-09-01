"""Seed the teaching-tour canvas desktop onboarding points new users at.

The tour is a self-demonstrating canvas: it teaches spaces, the agent, space
context, Self-driving, and canvases, and its last stop runs a live query so
reading about canvases is also watching one work. Seeded once per team into the general
space when the first onboarding session starts, through the same publish
pipeline as any other canvas (a real source version with declared
capabilities, plus a queued build), like ``welcome.seed_home_canvas``.
"""

from typing import Any
from uuid import UUID

from django.db import connection, transaction
from django.utils import timezone

from posthog.models.user import User

from products.canvas.backend import build_service
from products.canvas.backend.models import Canvas
from products.canvas.backend.source import synthetic_source_project

TEACHING_CANVAS_TEMPLATE_ID = "desktop-onboarding-teaching"
TEACHING_CANVAS_NAME = "Start here"

# Template ids the create API refuses, so a user-created canvas can never be
# mistaken for (or pre-claim and suppress) a PostHog-seeded one.
RESERVED_TEMPLATE_IDS = frozenset({TEACHING_CANVAS_TEMPLATE_ID})

TEACHING_CANVAS_DESCRIPTION = (
    "A short tour of PostHog Desktop for new users: spaces, the agent, space context, Self-driving, and canvases."
)

TEACHING_CANVAS_CONTEXT = (
    "This canvas is an onboarding tour for new PostHog Desktop users. It explains spaces, "
    "the agent, space context, Self-driving, and canvases, and shows a live unique-users "
    "chart. If you edit it, keep it short and plain."
)

TEACHING_CANVAS_CODE = """\
import { useEffect, useState } from "react";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  Heading,
  Skeleton,
  Text,
} from "@posthog/quill";
import { ArrowLeft, ArrowRight, Bot, BookOpen, Check, Hash, LayoutDashboard, PartyPopper, Radar } from "lucide-react";
import dayjs from "dayjs";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

const TOPICS = [
  {
    id: "spaces",
    icon: Hash,
    title: "Spaces",
    tagline: "Where work happens with your team",
    body: [
      "A space is a shared feed of work. #general is open to everyone in your workspace, and your personal space is only yours.",
      "Each space collects the tasks you start there, plus its own context and canvases.",
    ],
    prompts: ["What happened in this project this week?"],
  },
  {
    id: "agent",
    icon: Bot,
    title: "The agent",
    tagline: "Type what you want done",
    body: [
      "Every message you send in a space starts a task. The agent can query your product data, investigate errors, watch for problems, and open pull requests in your repos.",
      "You can follow along while it works, steer it mid-task, and pick up the thread later.",
    ],
    prompts: ["What are our top errors this week?", "Add PostHog to my repo and open a pull request."],
  },
  {
    id: "context",
    icon: BookOpen,
    title: "Context",
    tagline: "What the agent already knows",
    body: [
      "Each space keeps shared context that the agent reads before it starts any task. What your company does gets saved there, so you don't have to repeat yourself.",
      "Open a space's context page to read or edit it. Anything you correct there sticks for every future task.",
    ],
    prompts: ["Update this space's context with what my company does."],
  },
  {
    id: "self-driving",
    icon: Radar,
    title: "Self-driving",
    tagline: "PostHog watches for problems on its own",
    body: [
      "PostHog watches this project for things like errors, failing health checks, support tickets and metric swings. When something looks wrong, it writes up what it found and what it would do about it.",
      "Those write-ups go to Self-driving, the inbox in the left sidebar. Some arrive with a pull request already open for you to review.",
    ],
    prompts: ["What's waiting for me in Self-driving?"],
  },
  {
    id: "canvases",
    icon: LayoutDashboard,
    title: "Canvases",
    tagline: "Small apps that live in a space",
    body: [
      "Canvases are apps the agent builds for you: dashboards, forms, tools, prototypes. They can run live queries against your PostHog data.",
      "This page is a canvas, and the chart below is a live query running against your project as you read this. To make a canvas of your own, or change this one, ask the agent.",
    ],
    prompts: ["Build a canvas that charts signups by week."],
  },
];

const USERS_QUERY = {
  kind: "TrendsQuery",
  series: [{ kind: "EventsNode", event: null, name: "Unique users", math: "dau" }],
  interval: "day",
  dateRange: { date_from: "-30d" },
};

const TOUR_STYLES = `
@keyframes tour-fade-up { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: none; } }
@keyframes tour-slide-in { from { opacity: 0; transform: translateX(14px); } to { opacity: 1; transform: none; } }
@keyframes tour-pop { from { opacity: 0; transform: scale(0.95); } to { opacity: 1; transform: none; } }
.tour-fade-up { animation: tour-fade-up 0.35s cubic-bezier(0.2, 0.8, 0.2, 1) backwards; }
.tour-slide-in { animation: tour-slide-in 0.25s cubic-bezier(0.2, 0.8, 0.2, 1) backwards; }
.tour-pop { animation: tour-pop 0.3s cubic-bezier(0.2, 0.8, 0.2, 1) backwards; }
@media (prefers-reduced-motion: reduce) {
  .tour-fade-up, .tour-slide-in, .tour-pop { animation: none; }
}
`;

// Progress survives reloads only when the host answers ph.state. An old
// runtime without it degrades to session-only checks, never a crash.
const stateApi =
  typeof ph !== "undefined" && ph.state && typeof ph.state.get === "function" ? ph.state : null;

function IconChip({ icon: Icon }) {
  return (
    <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-border bg-muted">
      <Icon className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
    </div>
  );
}

function StopProgress({ current, seen }) {
  return (
    <div className="flex items-center gap-1.5" aria-hidden="true">
      {TOPICS.map((topic, index) => (
        <div
          key={topic.id}
          className={
            "h-1 w-6 rounded-full " +
            (index === current ? "bg-foreground" : seen[topic.id] ? "bg-muted-foreground" : "bg-border")
          }
        />
      ))}
    </div>
  );
}

function SeenCheck() {
  return (
    <div className="tour-pop mt-1 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-success">
      <Check className="h-3 w-3 text-success-foreground" aria-label="Seen" />
    </div>
  );
}

function ViewQueryDialog() {
  return (
    <Dialog>
      <DialogTrigger
        render={
          <Button variant="link-muted" size="sm">
            View query
          </Button>
        }
      />
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Query behind this chart</DialogTitle>
        </DialogHeader>
        <div className="max-h-80 overflow-auto whitespace-pre-wrap rounded bg-muted p-3 font-mono text-xs">
          {JSON.stringify(USERS_QUERY, null, 2)}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function LiveUsersCard() {
  const [state, setState] = useState({ loading: true, error: null, series: null });
  const [nonce, setNonce] = useState(0);
  useEffect(() => {
    let cancelled = false;
    setState({ loading: true, error: null, series: null });
    ph.query(USERS_QUERY)
      .then((response) => {
        if (cancelled) return;
        const series = response && response.results && response.results[0] ? response.results[0] : null;
        setState({ loading: false, error: null, series });
      })
      .catch((err) => {
        if (cancelled) return;
        setState({ loading: false, error: String((err && err.message) || err), series: null });
      });
    return () => {
      cancelled = true;
    };
  }, [nonce]);
  const data = state.series
    ? state.series.data.map((value, index) => ({
        day: state.series.days && state.series.days[index] ? dayjs(state.series.days[index]).format("MMM D") : "",
        value,
      }))
    : [];
  const empty = !state.loading && !state.error && (!data.length || data.every((point) => !point.value));
  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-2">
          <div className="flex flex-col gap-0.5">
            <CardTitle>Unique users by day</CardTitle>
            <CardDescription>Last 30 days, live from your project</CardDescription>
          </div>
          <ViewQueryDialog />
        </div>
      </CardHeader>
      <CardContent>
        {state.loading ? (
          <Skeleton className="h-[160px] w-full" />
        ) : state.error ? (
          <div className="flex items-center justify-between gap-2">
            <Text size="sm" variant="destructive">
              Couldn't load: {state.error}
            </Text>
            <Button variant="outline" size="sm" onClick={() => setNonce((value) => value + 1)}>
              Retry
            </Button>
          </div>
        ) : empty ? (
          <Text size="sm" variant="muted">
            No events yet. Once your project sends data to PostHog, this chart fills in on its own.
          </Text>
        ) : (
          <div className="h-[160px]">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: -16 }}>
                <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
                <XAxis dataKey="day" stroke="var(--muted-foreground)" fontSize={11} tickLine={false} axisLine={false} minTickGap={24} />
                <YAxis stroke="var(--muted-foreground)" fontSize={11} tickLine={false} axisLine={false} allowDecimals={false} />
                <Tooltip contentStyle={{ background: "var(--background)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }} />
                <Line type="monotone" dataKey="value" stroke="var(--primary)" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function HomeView({ onOpen, seen, seenCount, allSeen }) {
  return (
    <div className="tour-fade-up flex flex-col gap-6">
      <div className="flex items-start justify-between gap-3">
        <div className="flex flex-col gap-1.5">
          <Heading size="2xl" render={<h1 />}>
            How PostHog Desktop works
          </Heading>
          <Text variant="muted">A quick tour in five stops. Pick one.</Text>
        </div>
        <div className="mt-1 flex shrink-0 flex-col items-end gap-1.5">
          {allSeen ? (
            <Badge variant="success" className="tour-pop">
              Tour complete
            </Badge>
          ) : (
            <Text size="xs" variant="muted">
              {seenCount} of {TOPICS.length} seen
            </Text>
          )}
          <StopProgress current={-1} seen={seen} />
        </div>
      </div>
      {allSeen ? (
        <div className="tour-pop flex items-center gap-3 rounded-lg border border-border bg-muted p-4">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-success">
            <PartyPopper className="h-4 w-4 text-success-foreground" aria-hidden="true" />
          </div>
          <div className="flex flex-col gap-0.5">
            <Text weight="medium">You know your way around now</Text>
            <Text size="sm" variant="muted">
              Delete this canvas whenever you like, or ask the agent to build you a canvas of your own.
            </Text>
          </div>
        </div>
      ) : null}
      <div className="grid gap-3 sm:grid-cols-2">
        {TOPICS.map((topic, index) => (
          <div
            key={topic.id}
            className="tour-fade-up transition-transform duration-150 hover:-translate-y-0.5 motion-reduce:transition-none motion-reduce:hover:transform-none"
            style={{ animationDelay: 0.05 * index + 0.05 + "s" }}
          >
            <Button
              variant="outline"
              className="h-auto w-full whitespace-normal p-4 text-left"
              onClick={() => onOpen(topic.id)}
            >
              <div className="flex w-full items-start gap-3">
                <IconChip icon={topic.icon} />
                <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                  <Text weight="medium">{topic.title}</Text>
                  <Text size="sm" variant="muted">
                    {topic.tagline}
                  </Text>
                </div>
                {seen[topic.id] ? (
                  <SeenCheck />
                ) : (
                  <ArrowRight className="mt-1 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                )}
              </div>
            </Button>
          </div>
        ))}
      </div>
      <div className="border-t border-border pt-4">
        <Text size="sm" variant="muted">
          This page is a canvas: a small app that lives in this space. Delete it whenever you like.
        </Text>
      </div>
    </div>
  );
}

function DetailView({ topic, index, next, seen, onBack, onNext }) {
  return (
    <div className="tour-slide-in flex flex-col gap-5">
      <div className="flex items-center justify-between">
        <Button variant="link-muted" size="sm" onClick={onBack}>
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          All topics
        </Button>
        <StopProgress current={index} seen={seen} />
      </div>
      <div className="flex flex-col gap-3">
        <Text size="xs" variant="muted" className="uppercase tracking-wider">
          Stop {index + 1} of {TOPICS.length}
        </Text>
        <div className="flex items-center gap-3">
          <IconChip icon={topic.icon} />
          <div className="flex flex-col">
            <Heading size="2xl" render={<h1 />}>
              {topic.title}
            </Heading>
            <Text size="sm" variant="muted">
              {topic.tagline}
            </Text>
          </div>
        </div>
      </div>
      <div className="flex flex-col gap-3">
        {topic.body.map((paragraph) => (
          <Text key={paragraph}>{paragraph}</Text>
        ))}
      </div>
      {topic.id === "canvases" ? <LiveUsersCard /> : null}
      <div className="flex flex-col gap-2.5 rounded-lg border border-border bg-muted p-4">
        <Text size="sm" weight="medium">
          Try asking
        </Text>
        <div className="flex flex-col items-start gap-2">
          {topic.prompts.map((prompt) => (
            <div key={prompt} className="rounded-lg border border-border bg-background px-3 py-2">
              <Text size="sm">“{prompt}”</Text>
            </div>
          ))}
        </div>
      </div>
      <div className="flex justify-end border-t border-border pt-4">
        {next ? (
          <Button variant="outline" onClick={onNext}>
            Next: {next.title}
            <ArrowRight className="h-4 w-4" aria-hidden="true" />
          </Button>
        ) : (
          <Button variant="outline" onClick={onBack}>
            Back to all topics
          </Button>
        )}
      </div>
    </div>
  );
}

export default function StartHere() {
  const [topicId, setTopicId] = useState(null);
  const [seen, setSeen] = useState(null);
  useEffect(() => {
    let cancelled = false;
    if (!stateApi) {
      setSeen({});
      return;
    }
    stateApi
      .get("seen", { scope: "user" })
      .then((value) => {
        if (!cancelled) setSeen(value && typeof value === "object" ? value : {});
      })
      .catch(() => {
        if (!cancelled) setSeen({});
      });
    return () => {
      cancelled = true;
    };
  }, []);
  const seenMap = seen || {};
  const open = (id) => {
    const next = { ...seenMap, [id]: true };
    setSeen(next);
    if (stateApi) {
      stateApi.set("seen", next, { scope: "user" }).catch(() => {});
    }
    setTopicId(id);
  };
  const index = TOPICS.findIndex((topic) => topic.id === topicId);
  const topic = index === -1 ? null : TOPICS[index];
  const next = topic && index < TOPICS.length - 1 ? TOPICS[index + 1] : null;
  const seenCount = TOPICS.filter((entry) => seenMap[entry.id]).length;
  const allSeen = seen !== null && seenCount === TOPICS.length;
  return (
    <div className="h-screen overflow-y-auto bg-background">
      <style>{TOUR_STYLES}</style>
      <div className="mx-auto max-w-2xl px-6 py-12" key={topic ? topic.id : "home"}>
        {topic ? (
          <DetailView
            topic={topic}
            index={index}
            next={next}
            seen={seenMap}
            onBack={() => setTopicId(null)}
            onNext={() => next && open(next.id)}
          />
        ) : (
          <HomeView onOpen={open} seen={seenMap} seenCount={seenCount} allSeen={allSeen} />
        )}
      </div>
    </div>
  );
}
"""


def teaching_tour_project() -> dict[str, Any]:
    """The tour's source project (kept publishable by a contract test)."""
    project = synthetic_source_project(TEACHING_CANVAS_CODE)
    # The complete capability shape, not just the fields the tour uses: the
    # builder freezes this verbatim into the artifact manifest, and older
    # clients parse the manifest with every field required.
    project["capabilities"] = {
        "posthog": {
            "insights": [],
            "inlineQueries": True,
            "captureEvents": [],
            "state": ["user"],
            "actions": [],
        },
        "network": {"origins": []},
    }
    return project


def _publish_tour(canvas: Canvas, user: User) -> None:
    build_service.publish_source_project(
        canvas,
        project=teaching_tour_project(),
        prompt=TEACHING_CANVAS_NAME,
        name=None,
        has_expected_version=False,
        expected_version_id=None,
        task_id=None,
        created_by=user,
    )


def _lock_teaching_seed(team_id: int, channel_id: UUID) -> None:
    """Serialize seeding per space inside the current transaction.

    Two first sign-ins racing would otherwise both miss the read below and each
    seed a tour. Same posture as ``CanvasViewSet._lock_home_provisioning``: there
    is no row to lock before the first seed, so a transaction-scoped advisory
    lock guards the read-then-create window.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            [f"canvas_teaching:{team_id}:{channel_id}"],
        )


def seed_teaching_canvas(*, team_id: int, channel_id: UUID, user: User, refresh: bool = False) -> UUID | None:
    """Get or seed the team's teaching-tour canvas in its general space.

    Returns ``None`` when a previously seeded tour was deleted: someone removed it
    on purpose, so a later joiner's onboarding does not put it back. A row whose
    first publish failed gets its publish retried, so a transient storage outage
    heals on the next sign-in. Raises on failure; callers treat seeding as
    best-effort.

    ``refresh`` is for the onboarding test tools, which reseed the same space over
    and over: it revives a deleted tour and republishes the current source, so
    deleting the canvas is how a tester resets it rather than how they lose it.
    """
    with transaction.atomic():
        _lock_teaching_seed(team_id, channel_id)
        existing = (
            Canvas.objects.for_team(team_id)
            .filter(channel_id=channel_id, template_id=TEACHING_CANVAS_TEMPLATE_ID)
            .order_by("created_at")
            .first()
        )
        if existing is not None:
            if existing.deleted and not refresh:
                return None
            if existing.deleted:
                existing.deleted = False
                existing.pinned_at = timezone.now()
                existing.save(update_fields=["deleted", "pinned_at"])
            if refresh or existing.current_source_version_id is None:
                _publish_tour(existing, user)
            return existing.id
        canvas = Canvas.objects.create(
            team_id=team_id,
            channel_id=channel_id,
            name=TEACHING_CANVAS_NAME,
            kind=Canvas.KIND_FREEFORM,
            template_id=TEACHING_CANVAS_TEMPLATE_ID,
            description=TEACHING_CANVAS_DESCRIPTION,
            context=TEACHING_CANVAS_CONTEXT,
            pinned_at=timezone.now(),
            created_by=user,
        )
        _publish_tour(canvas, user)
        return canvas.id
