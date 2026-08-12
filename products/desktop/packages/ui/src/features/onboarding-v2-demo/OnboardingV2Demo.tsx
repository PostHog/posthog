import { Button, cn } from "@posthog/quill";
import { motion } from "framer-motion";
import { useCallback, useEffect, useRef, useState } from "react";

const DEMO_DISMISSED_KEY = "ph-onboarding-v2-demo-dismissed";

export function useOnboardingV2Demo(): { active: boolean; exit: () => void } {
  const [active, setActive] = useState(() => {
    try {
      return window.localStorage.getItem(DEMO_DISMISSED_KEY) !== "1";
    } catch {
      return true;
    }
  });
  const exit = useCallback(() => {
    try {
      window.localStorage.setItem(DEMO_DISMISSED_KEY, "1");
    } catch {
      // localStorage unavailable; demo just won't stay dismissed
    }
    setActive(false);
  }, []);
  return { active, exit };
}

type Phase = "welcome" | "project" | "github" | "app";

interface StreamLine {
  label: string;
  fact: string;
}

const INTRO_LINES: StreamLine[] = [
  {
    label: "Reading hogflix.com",
    fact: "Streaming service. Short films, subscriptions, web and mobile apps.",
  },
  {
    label: "Scanning hogflix/hogflix-app",
    fact: "TypeScript monorepo. Next.js frontend, Django API, 34 contributors.",
  },
  {
    label: "Looking at your PostHog data",
    fact: "214 events, 12.4k weekly users. Checkout errors climbing since Tuesday.",
  },
  { label: "Building your welcome canvas", fact: "" },
];

const INVESTIGATION_LINES: StreamLine[] = [
  {
    label: "Pulling PaymentDeclinedError traces",
    fact: "412 occurrences this week, all from the new payment client.",
  },
  {
    label: "Reading the v2.14 diff",
    fact: "Retries were disabled in payment-client.ts.",
  },
  { label: "Drafting a fix", fact: "" },
];

const SYNTHESIS =
  "Hogflix streams short films to 12.4k weekly viewers on web and mobile. The app is a TypeScript monorepo with a Next.js frontend and a Django API. Checkout errors have tripled since the v2.14 release on Tuesday.";

const SUGGESTIONS = [
  {
    title: "Investigate the checkout error spike",
    why: "PaymentDeclinedError is up 3.1x since the v2.14 release.",
    wired: true,
  },
  {
    title: "Instrument the new search flow",
    why: "Search shipped last week and sends no events yet.",
    wired: false,
  },
  {
    title: "Fix the signup drop-off",
    why: "38% of users leave between plan selection and payment.",
    wired: false,
  },
  {
    title: "Set up a weekly viewer report",
    why: "A canvas that keeps itself up to date with retention and top titles.",
    wired: false,
  },
];

const rise = {
  initial: { opacity: 0, y: 8 },
  animate: { opacity: 1, y: 0 },
};

function DemoSpinner({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "size-3.5 animate-spin rounded-full border-2 border-gray-6 border-t-gray-11",
        className,
      )}
    />
  );
}

function StepDots({ step }: { step: number }) {
  return (
    <div className="mt-6 flex justify-center gap-2">
      {[0, 1, 2].map((i) => (
        <div
          key={i}
          className={cn(
            "size-1.5 rounded-full",
            i === step ? "bg-primary" : "bg-gray-6",
          )}
        />
      ))}
    </div>
  );
}

function WizardCard({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-full items-center justify-center bg-background">
      <motion.div
        {...rise}
        className="w-[430px] rounded-xl border border-border bg-chrome p-8"
      >
        <div className="mb-5 flex size-11 items-center justify-center rounded-lg bg-primary text-2xl">
          🦔
        </div>
        {children}
      </motion.div>
    </div>
  );
}

function WelcomeStep({ onNext }: { onNext: () => void }) {
  return (
    <WizardCard>
      <h1 className="mb-2 font-semibold text-foreground text-xl">
        Agents that know your company
      </h1>
      <p className="mb-6 text-muted-foreground text-sm">
        PostHog Desktop connects your code, your product data, and your team, so
        every session starts with context.
      </p>
      <Button variant="primary" className="w-full" onClick={onNext}>
        Sign in with PostHog
      </Button>
      <StepDots step={0} />
    </WizardCard>
  );
}

function ProjectStep({ onNext }: { onNext: () => void }) {
  const projects = [
    { glyph: "🎬", name: "Hogflix", meta: "US cloud · hogflix.com" },
    { glyph: "🧪", name: "Hogflix staging", meta: "US cloud" },
  ];
  return (
    <WizardCard>
      <h1 className="mb-2 font-semibold text-foreground text-xl">
        Choose a project
      </h1>
      <p className="mb-6 text-muted-foreground text-sm">
        Your agents read this project's data.
      </p>
      {projects.map((p) => (
        <button
          key={p.name}
          type="button"
          onClick={onNext}
          className="mb-2.5 flex w-full items-center gap-3 rounded-lg border border-border p-3 text-left transition-colors hover:bg-gray-3"
        >
          <div className="flex size-8 items-center justify-center rounded-lg bg-gray-4">
            {p.glyph}
          </div>
          <div>
            <div className="font-medium text-foreground text-sm">{p.name}</div>
            <div className="text-muted-foreground text-xs">{p.meta}</div>
          </div>
        </button>
      ))}
      <StepDots step={1} />
    </WizardCard>
  );
}

function GithubStep({
  speedRef,
  onNext,
}: {
  speedRef: React.MutableRefObject<number>;
  onNext: () => void;
}) {
  const [status, setStatus] = useState<"idle" | "connecting" | "connected">(
    "idle",
  );
  useEffect(() => {
    if (status !== "connecting") return;
    const t = setTimeout(() => setStatus("connected"), 1300 * speedRef.current);
    return () => clearTimeout(t);
  }, [status, speedRef]);

  const repos = [
    "hogflix/hogflix-app",
    "hogflix/infra",
    "hogflix/marketing-site",
  ];

  return (
    <WizardCard>
      <h1 className="mb-2 font-semibold text-foreground text-xl">
        Connect GitHub
      </h1>
      <p className="mb-6 text-muted-foreground text-sm">
        Cloud agents work on your repos through the GitHub app. Choose the repos
        to give them.
      </p>
      {status === "connected" && (
        <motion.div
          {...rise}
          className="mb-4 rounded-lg border border-border p-3.5"
        >
          <div className="mb-2 flex items-center gap-2 font-medium text-foreground text-sm">
            <span className="text-green-600 dark:text-green-500">✓</span>
            Connected as hogflix
          </div>
          {repos.map((r) => (
            <div
              key={r}
              className="flex items-center gap-2 py-1 font-mono text-muted-foreground text-xs"
            >
              <span className="text-green-600 dark:text-green-500">✓</span>
              {r}
            </div>
          ))}
        </motion.div>
      )}
      {status !== "connected" ? (
        <Button
          variant="primary"
          className="w-full"
          disabled={status === "connecting"}
          onClick={() => setStatus("connecting")}
        >
          {status === "connecting" ? (
            <span className="flex items-center gap-2">
              <DemoSpinner className="border-white/30 border-t-white" />
              Connecting
            </span>
          ) : (
            "Connect GitHub"
          )}
        </Button>
      ) : (
        <Button variant="primary" className="w-full" onClick={onNext}>
          Continue
        </Button>
      )}
      <div className="mt-2.5 text-center">
        <button
          type="button"
          onClick={onNext}
          className="p-1.5 text-muted-foreground text-xs hover:text-foreground"
        >
          Skip for now
        </button>
      </div>
      <StepDots step={2} />
    </WizardCard>
  );
}

function StreamLineRow({
  line,
  state,
}: {
  line: StreamLine;
  state: "running" | "done";
}) {
  return (
    <motion.div {...rise} className="flex items-baseline gap-2.5 py-1.5">
      <div className="w-4 flex-none text-center">
        {state === "running" ? (
          <DemoSpinner className="relative top-0.5 inline-block" />
        ) : (
          <span className="font-semibold text-green-600 dark:text-green-500">
            ✓
          </span>
        )}
      </div>
      <div>
        <div className="text-foreground text-sm">{line.label}</div>
        {state === "done" && line.fact ? (
          <div className="text-muted-foreground text-xs">{line.fact}</div>
        ) : null}
      </div>
    </motion.div>
  );
}

function SessionCard({
  title,
  lines,
  visibleCount,
  done,
}: {
  title: string;
  lines: StreamLine[];
  visibleCount: number;
  done: boolean;
}) {
  return (
    <motion.div
      {...rise}
      className="mb-3.5 max-w-2xl rounded-xl border border-border bg-chrome p-4"
    >
      <div className="flex items-center gap-2.5">
        {done ? (
          <span className="font-semibold text-green-600 dark:text-green-500">
            ✓
          </span>
        ) : (
          <DemoSpinner />
        )}
        <span className="font-semibold text-foreground text-sm">{title}</span>
        <span
          className={cn(
            "rounded-full px-2 py-0.5 font-semibold text-[11px]",
            done
              ? "bg-gray-4 text-muted-foreground"
              : "bg-green-500/15 text-green-600 dark:text-green-500",
          )}
        >
          {done ? "Done" : "Running"}
        </span>
      </div>
      <div className="mt-2">
        {lines.slice(0, visibleCount).map((line, i) => (
          <StreamLineRow
            key={line.label}
            line={line}
            state={i < visibleCount - 1 || done ? "done" : "running"}
          />
        ))}
      </div>
    </motion.div>
  );
}

function Tile({
  label,
  value,
  delta,
  deltaTone,
  points,
  stroke,
  mono,
}: {
  label: string;
  value: string;
  delta: string;
  deltaTone: "up" | "bad" | "flat";
  points: string;
  stroke: string;
  mono?: boolean;
}) {
  return (
    <motion.div
      {...rise}
      className="rounded-lg border border-border bg-background p-3"
    >
      <div className="text-muted-foreground text-xs">{label}</div>
      <div
        className={cn(
          "font-semibold text-foreground",
          mono ? "font-mono text-sm" : "text-lg",
        )}
      >
        {value}
      </div>
      <div
        className={cn(
          "text-xs",
          deltaTone === "up" && "text-green-600 dark:text-green-500",
          deltaTone === "bad" && "text-orange-500",
          deltaTone === "flat" && "text-muted-foreground",
        )}
      >
        {delta}
      </div>
      <svg
        viewBox="0 0 100 26"
        preserveAspectRatio="none"
        className="mt-2 h-6 w-full"
        role="presentation"
      >
        <polyline points={points} fill="none" stroke={stroke} strokeWidth="2" />
      </svg>
    </motion.div>
  );
}

interface IntroProgress {
  visibleLines: number;
  sessionDone: boolean;
  canvasVisible: boolean;
  synthesis: string;
  tilesShown: number;
  suggestionsShown: number;
  inviteShown: boolean;
}

const INTRO_START: IntroProgress = {
  visibleLines: 0,
  sessionDone: false,
  canvasVisible: false,
  synthesis: "",
  tilesShown: 0,
  suggestionsShown: 0,
  inviteShown: false,
};

function AppPhase({
  speedRef,
  onExit,
}: {
  speedRef: React.MutableRefObject<number>;
  onExit: () => void;
}) {
  const [intro, setIntro] = useState<IntroProgress>(INTRO_START);
  const [view, setView] = useState<"general" | "investigation">("general");
  const [investigationStarted, setInvestigationStarted] = useState(false);
  const [investigationLines, setInvestigationLines] = useState(0);
  const [investigationDone, setInvestigationDone] = useState(false);
  const [calloutVisible, setCalloutVisible] = useState(true);
  const [toast, setToast] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const sleep = (ms: number) =>
      new Promise<void>((resolve) =>
        setTimeout(resolve, ms * speedRef.current),
      );
    const patch = (p: Partial<IntroProgress>) => {
      if (alive) setIntro((s) => ({ ...s, ...p }));
    };
    const run = async () => {
      await sleep(700);
      for (let i = 1; i <= INTRO_LINES.length; i++) {
        patch({ visibleLines: i });
        await sleep(1500);
      }
      patch({ sessionDone: true });
      setCalloutVisible(false);
      await sleep(400);
      patch({ canvasVisible: true });
      for (let i = 1; i <= SYNTHESIS.length; i++) {
        if (!alive) return;
        patch({ synthesis: SYNTHESIS.slice(0, i) });
        await sleep(10);
      }
      await sleep(300);
      for (let i = 1; i <= 3; i++) {
        patch({ tilesShown: i });
        await sleep(350);
      }
      await sleep(300);
      for (let i = 1; i <= SUGGESTIONS.length; i++) {
        patch({ suggestionsShown: i });
        await sleep(180);
      }
      await sleep(400);
      patch({ inviteShown: true });
    };
    void run();
    return () => {
      alive = false;
    };
  }, [speedRef]);

  useEffect(() => {
    if (!investigationStarted) return;
    let alive = true;
    const sleep = (ms: number) =>
      new Promise<void>((resolve) =>
        setTimeout(resolve, ms * speedRef.current),
      );
    const run = async () => {
      await sleep(600);
      for (let i = 1; i <= INVESTIGATION_LINES.length; i++) {
        if (!alive) return;
        setInvestigationLines(i);
        await sleep(1500);
      }
      if (!alive) return;
      setInvestigationDone(true);
    };
    void run();
    return () => {
      alive = false;
    };
  }, [investigationStarted, speedRef]);

  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 2200);
    return () => clearTimeout(t);
  }, [toast]);

  return (
    <div className="relative flex h-full bg-background text-foreground">
      <div className="flex w-[232px] flex-none flex-col border-border border-r bg-chrome p-2.5">
        <div className="flex items-center gap-2 px-1.5 pt-1 pb-3.5 font-semibold text-sm">
          <div className="flex size-6 items-center justify-center rounded-md bg-primary text-xs">
            🦔
          </div>
          Hogflix
        </div>
        <div className="px-1.5 pt-2 pb-1.5 font-semibold text-[11px] text-gray-10 uppercase tracking-wider">
          Spaces
        </div>
        <div className="flex items-center gap-2 rounded-md bg-gray-3 px-1.5 py-1.5 text-foreground text-sm">
          <span className="w-3.5 text-center text-gray-10">#</span> general
          {!intro.sessionDone && (
            <span className="ml-auto size-1.5 animate-pulse rounded-full bg-green-500" />
          )}
        </div>
        <div className="flex items-center gap-2 px-1.5 py-1.5 text-muted-foreground text-sm">
          <span className="w-3.5 text-center">🔒</span> personal
        </div>
        <div className="px-1.5 py-2.5 text-gray-10 text-xs italic">
          New spaces appear as work accumulates.
        </div>
        <div className="mt-auto flex items-center gap-2 border-border border-t px-1.5 pt-2.5">
          <div className="flex size-6 items-center justify-center rounded-full bg-blue-500 font-bold text-[11px] text-white">
            A
          </div>
          <span className="text-muted-foreground text-xs">
            annika@hogflix.com
          </span>
        </div>
      </div>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex h-11 flex-none items-center gap-2 border-border border-b px-4 font-semibold text-sm">
          <span className="text-gray-10">#</span> general
          <span className="font-normal text-gray-10 text-xs">
            Where unrouted work lands
          </span>
        </div>
        <div className="flex-1 overflow-y-auto p-4">
          <div className={view === "general" ? "" : "hidden"}>
            <SessionCard
              title="Getting to know Hogflix"
              lines={INTRO_LINES}
              visibleCount={intro.visibleLines}
              done={intro.sessionDone}
            />
            {intro.canvasVisible && (
              <motion.div
                {...rise}
                className="max-w-2xl rounded-xl border border-border bg-chrome p-5"
              >
                <div className="mb-3 flex items-center gap-2.5">
                  <h2 className="font-semibold text-base text-foreground">
                    Hogflix at a glance
                  </h2>
                  <span className="rounded bg-primary/15 px-2 py-0.5 font-semibold text-[11px] text-primary">
                    Canvas
                  </span>
                </div>
                <p className="min-h-10 max-w-[62ch] text-muted-foreground text-sm">
                  {intro.synthesis}
                  {intro.synthesis.length < SYNTHESIS.length && (
                    <span className="ml-0.5 inline-block h-3.5 w-1.5 animate-pulse bg-primary align-[-2px]" />
                  )}
                </p>
                <div className="mt-4 grid grid-cols-3 gap-2.5">
                  {intro.tilesShown >= 1 && (
                    <Tile
                      label="Weekly active users"
                      value="12,480"
                      delta="↑ 8% vs last week"
                      deltaTone="up"
                      points="0,20 14,18 28,19 42,15 56,14 70,11 84,9 100,5"
                      stroke="#51cf66"
                    />
                  )}
                  {intro.tilesShown >= 2 && (
                    <Tile
                      label="Top event this week"
                      value="video_played"
                      mono
                      delta="1.2M events"
                      deltaTone="flat"
                      points="0,14 14,12 28,15 42,10 56,13 70,9 84,11 100,8"
                      stroke="#4dabf7"
                    />
                  )}
                  {intro.tilesShown >= 3 && (
                    <Tile
                      label="Checkout errors"
                      value="×3.1"
                      delta="since v2.14 on Tuesday"
                      deltaTone="bad"
                      points="0,22 14,21 28,22 42,20 56,21 70,12 84,7 100,3"
                      stroke="#ff922b"
                    />
                  )}
                </div>
                {intro.suggestionsShown > 0 && (
                  <div className="mt-4 mb-2.5 font-semibold text-[11px] text-gray-10 uppercase tracking-wider">
                    Suggested next sessions
                  </div>
                )}
                <div className="grid grid-cols-2 gap-2.5">
                  {SUGGESTIONS.slice(0, intro.suggestionsShown).map((s) => (
                    <motion.button
                      {...rise}
                      key={s.title}
                      type="button"
                      title={
                        s.wired ? undefined : "Not wired in this prototype"
                      }
                      onClick={
                        s.wired
                          ? () => {
                              setView("investigation");
                              setInvestigationStarted(true);
                            }
                          : undefined
                      }
                      className="rounded-lg border border-border bg-background p-3.5 text-left transition-colors hover:bg-gray-3"
                    >
                      <div className="mb-0.5 font-medium text-foreground text-sm">
                        {s.title}
                      </div>
                      <div className="text-muted-foreground text-xs">
                        {s.why}
                      </div>
                      <div className="mt-2 font-semibold text-primary text-xs">
                        Start session →
                      </div>
                    </motion.button>
                  ))}
                </div>
                {intro.inviteShown && (
                  <motion.div
                    {...rise}
                    className="mt-4 flex items-center justify-between gap-3.5 border-border border-t pt-4"
                  >
                    <p className="max-w-[46ch] text-muted-foreground text-xs">
                      Sessions and canvases here are shared with your whole
                      space. Hogflix has 4 teammates on GitHub who aren't here
                      yet.
                    </p>
                    <Button
                      variant="primary"
                      size="sm"
                      onClick={() => setToast("Invite link copied")}
                    >
                      Invite teammates
                    </Button>
                  </motion.div>
                )}
              </motion.div>
            )}
          </div>

          <div className={view === "investigation" ? "" : "hidden"}>
            <button
              type="button"
              onClick={() => setView("general")}
              className="mb-3 flex items-center gap-1.5 text-muted-foreground text-xs hover:text-foreground"
            >
              ← # general
            </button>
            {investigationStarted && (
              <SessionCard
                title="Investigate the checkout error spike"
                lines={INVESTIGATION_LINES}
                visibleCount={investigationLines}
                done={investigationDone}
              />
            )}
            {investigationDone && (
              <motion.div
                {...rise}
                className="max-w-2xl rounded-xl border border-border border-dashed bg-chrome p-4"
              >
                <div className="font-semibold text-foreground text-sm">
                  End of the prototype
                </div>
                <p className="mt-1 mb-3.5 text-muted-foreground text-xs">
                  In the real app this session continues to a pull request you
                  can review.
                </p>
                <div className="flex gap-2.5">
                  <Button variant="outline" onClick={() => setView("general")}>
                    Back to the canvas
                  </Button>
                  <Button variant="primary" onClick={onExit}>
                    Exit demo
                  </Button>
                </div>
              </motion.div>
            )}
          </div>
        </div>
      </div>

      {calloutVisible && (
        <motion.div
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.8 }}
          className="pointer-events-none absolute top-[104px] left-[240px] rounded-lg border border-border bg-chrome px-2.5 py-1.5 text-foreground text-xs shadow-lg"
        >
          Your spaces live here
        </motion.div>
      )}
      {toast && (
        <div className="-translate-x-1/2 absolute bottom-4 left-1/2 rounded-lg border border-border bg-chrome px-3.5 py-2 text-foreground text-xs shadow-lg">
          {toast}
        </div>
      )}
    </div>
  );
}

export function OnboardingV2Demo({ onExit }: { onExit: () => void }) {
  const [phase, setPhase] = useState<Phase>("welcome");
  const [runKey, setRunKey] = useState(0);
  const [fast, setFast] = useState(false);
  const speedRef = useRef(1);

  const restart = useCallback(() => {
    setPhase("welcome");
    setRunKey((k) => k + 1);
  }, []);

  useEffect(() => {
    speedRef.current = fast ? 0.12 : 1;
  }, [fast]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "f" || e.key === "F") setFast((v) => !v);
      if (e.key === "r" || e.key === "R") restart();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [restart]);

  return (
    <div className="relative h-full" key={runKey}>
      {phase === "welcome" && (
        <WelcomeStep onNext={() => setPhase("project")} />
      )}
      {phase === "project" && <ProjectStep onNext={() => setPhase("github")} />}
      {phase === "github" && (
        <GithubStep speedRef={speedRef} onNext={() => setPhase("app")} />
      )}
      {phase === "app" && <AppPhase speedRef={speedRef} onExit={onExit} />}
      <div className="absolute right-3.5 bottom-3 z-10 flex gap-2 text-[11px] text-gray-10">
        <button
          type="button"
          onClick={() => setFast((v) => !v)}
          className={cn(
            "rounded-md border border-border bg-chrome px-2 py-0.5 hover:text-foreground",
            fast && "border-primary text-primary",
          )}
        >
          Fast · F
        </button>
        <button
          type="button"
          onClick={restart}
          className="rounded-md border border-border bg-chrome px-2 py-0.5 hover:text-foreground"
        >
          Restart · R
        </button>
        <button
          type="button"
          onClick={onExit}
          className="rounded-md border border-border bg-chrome px-2 py-0.5 hover:text-foreground"
        >
          Exit demo
        </button>
      </div>
    </div>
  );
}
