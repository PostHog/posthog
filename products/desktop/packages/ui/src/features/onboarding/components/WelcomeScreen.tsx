import {
  ArrowRight,
  ChartLine,
  Cloud,
  GitPullRequest,
  Robot,
  Tray,
} from "@phosphor-icons/react";
import { explorerHog } from "@posthog/ui/assets/hedgehogs";
import codeReviewDarkPoster from "@posthog/ui/features/onboarding/assets/code-review-dark.jpg";
import codeReviewDark from "@posthog/ui/features/onboarding/assets/code-review-dark.mp4";
import codeReviewLightPoster from "@posthog/ui/features/onboarding/assets/code-review-light.jpg";
import codeReviewLight from "@posthog/ui/features/onboarding/assets/code-review-light.mp4";
import commandCenterDarkPoster from "@posthog/ui/features/onboarding/assets/command-center-dark.jpg";
import commandCenterDark from "@posthog/ui/features/onboarding/assets/command-center-dark.mp4";
import commandCenterLightPoster from "@posthog/ui/features/onboarding/assets/command-center-light.jpg";
import commandCenterLight from "@posthog/ui/features/onboarding/assets/command-center-light.mp4";
import phcContextDarkPoster from "@posthog/ui/features/onboarding/assets/phc-context-dark.jpg";
import phcContextDark from "@posthog/ui/features/onboarding/assets/phc-context-dark.mp4";
import phcContextLightPoster from "@posthog/ui/features/onboarding/assets/phc-context-light.jpg";
import phcContextLight from "@posthog/ui/features/onboarding/assets/phc-context-light.mp4";
import phcHarnessDarkPoster from "@posthog/ui/features/onboarding/assets/phc-harness-dark.jpg";
import phcHarnessDark from "@posthog/ui/features/onboarding/assets/phc-harness-dark.mp4";
import phcHarnessLightPoster from "@posthog/ui/features/onboarding/assets/phc-harness-light.jpg";
import phcHarnessLight from "@posthog/ui/features/onboarding/assets/phc-harness-light.mp4";
import signalsInboxDarkPoster from "@posthog/ui/features/onboarding/assets/signals-inbox-dark.jpg";
import signalsInboxDark from "@posthog/ui/features/onboarding/assets/signals-inbox-dark.mp4";
import signalsInboxLightPoster from "@posthog/ui/features/onboarding/assets/signals-inbox-light.jpg";
import signalsInboxLight from "@posthog/ui/features/onboarding/assets/signals-inbox-light.mp4";
import { FeatureBentoCard } from "@posthog/ui/features/onboarding/components/FeatureBentoCard";
import { StepActions } from "@posthog/ui/features/onboarding/components/StepActions";
import Logo from "@posthog/ui/primitives/Logo";
import { OnboardingHogTip } from "@posthog/ui/primitives/OnboardingHogTip";
import { useThemeStore } from "@posthog/ui/shell/themeStore";
import { Button, Flex, Text } from "@radix-ui/themes";
import { motion, type Transition } from "framer-motion";
import {
  type ReactNode,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";

type MediaId =
  | "code-review"
  | "command-center"
  | "phc-context"
  | "phc-harness"
  | "signals-inbox";

interface MediaDef {
  light: { video: string; poster: string };
  dark: { video: string; poster: string };
  /** Seconds into the clip the still is taken from; playback starts/loops here. */
  startTime: number;
}

/** Demo media per feature, keyed per theme; resolved at render. */
const MEDIA: Record<MediaId, MediaDef> = {
  "code-review": {
    light: { video: codeReviewLight, poster: codeReviewLightPoster },
    dark: { video: codeReviewDark, poster: codeReviewDarkPoster },
    startTime: 3,
  },
  "command-center": {
    light: { video: commandCenterLight, poster: commandCenterLightPoster },
    dark: { video: commandCenterDark, poster: commandCenterDarkPoster },
    startTime: 0,
  },
  "phc-context": {
    light: { video: phcContextLight, poster: phcContextLightPoster },
    dark: { video: phcContextDark, poster: phcContextDarkPoster },
    startTime: 0,
  },
  "phc-harness": {
    light: { video: phcHarnessLight, poster: phcHarnessLightPoster },
    dark: { video: phcHarnessDark, poster: phcHarnessDarkPoster },
    startTime: 0,
  },
  "signals-inbox": {
    light: { video: signalsInboxLight, poster: signalsInboxLightPoster },
    dark: { video: signalsInboxDark, poster: signalsInboxDarkPoster },
    startTime: 0,
  },
};

interface FeatureDef {
  icon: ReactNode;
  title: string;
  description: string;
  /** Marks a card that shows a looping demo video instead of a placeholder. */
  media?: MediaId;
}

const FEATURES: FeatureDef[] = [
  {
    icon: <ChartLine size={28} />,
    title: "Product data as context",
    description:
      "Built-in context on analytics, session replays, experiments, feature flags, and more.",
    media: "phc-context",
  },
  {
    icon: <Tray size={26} />,
    title: "Your signals inbox",
    description:
      "Automatically surfaces the highest-impact work from your product data so you always know what to do next.",
    media: "signals-inbox",
  },
  {
    icon: <Robot size={22} />,
    title: "Your pick of Claude Code or Codex",
    description:
      "PostHog is harness-agnostic – both Anthropic and OpenAI supported.",
    media: "phc-harness",
  },
  {
    icon: <Cloud size={22} />,
    title: "Build non-stop",
    description:
      "Run tasks in parallel across local and cloud environments - even while you're away.",
    media: "command-center",
  },
  {
    icon: <GitPullRequest size={22} />,
    title: "Review and ship with confidence",
    description:
      "Inline diffs, AI-assisted code review and PR creation in a single flow.",
    media: "code-review",
  },
];

// Bento geometry (px). Cards are absolutely positioned into these slots and
// animate between them, so the whole grid slides around rather than snapping.
const GAP = 12;
const ROW0_HEIGHT = 288;
const ROW1_HEIGHT = 224;
const ROW1_TOP = ROW0_HEIGHT + GAP;
const GRID_HEIGHT = ROW1_TOP + ROW1_HEIGHT;

interface Rect {
  x: number;
  y: number;
  width: number;
  height: number;
}

/** Slot rectangles for a given container width. Slot 0 is the large cell. */
function slotRects(width: number): Rect[] {
  const colWidth = (width - 5 * GAP) / 6;
  const left = (col: number) => col * (colWidth + GAP);
  const span2 = 2 * colWidth + GAP;
  const span4 = 4 * colWidth + 3 * GAP;
  return [
    { x: left(0), y: 0, width: span4, height: ROW0_HEIGHT },
    { x: left(4), y: 0, width: span2, height: ROW0_HEIGHT },
    { x: left(0), y: ROW1_TOP, width: span2, height: ROW1_HEIGHT },
    { x: left(2), y: ROW1_TOP, width: span2, height: ROW1_HEIGHT },
    { x: left(4), y: ROW1_TOP, width: span2, height: ROW1_HEIGHT },
  ];
}

/** Spring so every card glides to its new slot together. */
const SLIDE_TRANSITION: Transition = {
  type: "spring",
  stiffness: 320,
  damping: 34,
};

interface WelcomeScreenProps {
  onNext: () => void;
}

/** Pointer events are suppressed for this long so the reflow doesn't thrash. */
const REFLOW_MS = 550;

export function WelcomeScreen({ onNext }: WelcomeScreenProps) {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  // order[slot] = feature index currently occupying that slot.
  const [order, setOrder] = useState(() => FEATURES.map((_, index) => index));
  const [isReflowing, setIsReflowing] = useState(false);
  const [gridWidth, setGridWidth] = useState(0);
  const isDarkMode = useThemeStore((state) => state.isDarkMode);
  const gridRef = useRef<HTMLDivElement>(null);

  // Measure the grid so slot rectangles stay correct and responsive.
  useLayoutEffect(() => {
    const element = gridRef.current;
    if (!element) return;
    const update = () => setGridWidth(element.clientWidth);
    update();
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  // Re-enable pointer events once the slide has settled.
  useEffect(() => {
    if (!isReflowing) return;
    const timeout = setTimeout(() => setIsReflowing(false), REFLOW_MS);
    return () => clearTimeout(timeout);
  }, [isReflowing]);

  const handleMouseEnter = (index: number) => {
    setHoveredIndex(index);
  };

  const handleMouseLeave = () => {
    setHoveredIndex(null);
  };

  // Rotate the order so the clicked card moves into the large slot and every
  // other card shifts along with it (keeping their relative order).
  const handleSelect = (index: number) => {
    const slot = order.indexOf(index);
    if (slot <= 0) return; // already in the large slot
    setIsReflowing(true);
    setOrder((prev) => [...prev.slice(slot), ...prev.slice(0, slot)]);
  };

  const rects = slotRects(gridWidth);
  // Only the featured (large) card plays. Hover just moves the highlight.
  const featuredIndex = order[0];

  return (
    <Flex align="center" height="100%" px="8">
      <Flex
        direction="column"
        align="center"
        className="h-full w-full pt-[24px] pb-[40px]"
      >
        <Flex
          direction="column"
          align="center"
          className="min-h-0 w-full flex-1"
        >
          <Flex
            direction="column"
            align="start"
            className="mx-0 my-auto w-full max-w-[760px] gap-6 overflow-hidden"
          >
            <Flex direction="row" align="center" gap="3">
              <Text
                /** Very specifically 25px text to be the same size as the Logo's font size */
                className="font-bold text-(--gray-12) text-[25px] tracking-[-0.05em]"
              >
                Welcome to
              </Text>
              <Logo />
            </Flex>

            <div
              ref={gridRef}
              className="relative w-full overflow-hidden rounded-lg"
              style={{
                height: GRID_HEIGHT,
                pointerEvents: isReflowing ? "none" : undefined,
              }}
            >
              {gridWidth > 0 &&
                FEATURES.map((feature, index) => {
                  const slot = order.indexOf(index);
                  const rect = rects[slot];
                  const mediaDef = feature.media
                    ? MEDIA[feature.media]
                    : undefined;
                  const media = mediaDef?.[isDarkMode ? "dark" : "light"];
                  return (
                    <motion.div
                      key={feature.title}
                      className="absolute top-0 left-0"
                      initial={false}
                      animate={{
                        x: rect.x,
                        y: rect.y,
                        width: rect.width,
                        height: rect.height,
                      }}
                      transition={SLIDE_TRANSITION}
                    >
                      <FeatureBentoCard
                        icon={feature.icon}
                        title={feature.title}
                        description={feature.description}
                        active={
                          index === featuredIndex && hoveredIndex === null
                        }
                        index={index}
                        videoSrc={media?.video}
                        posterSrc={media?.poster}
                        videoStartTime={mediaDef?.startTime}
                        shouldPlay={index === featuredIndex}
                        onSelect={
                          slot === 0 ? undefined : () => handleSelect(index)
                        }
                        onMouseEnter={() => handleMouseEnter(index)}
                        onMouseLeave={handleMouseLeave}
                      />
                    </motion.div>
                  );
                })}
            </div>
          </Flex>
        </Flex>

        <Flex direction="column" align="center" className="shrink-0 pt-[16px]">
          <OnboardingHogTip
            hogSrc={explorerHog}
            message="Let's get you set up! It only takes a minute."
          />
          <StepActions delay={0.25}>
            <Button size="3" onClick={onNext}>
              Start shipping
              <ArrowRight size={16} weight="bold" />
            </Button>
          </StepActions>
        </Flex>
      </Flex>
    </Flex>
  );
}
