import {
  ArrowLeft,
  ArrowRight,
  Folder,
  type Icon,
  PlugsConnected,
  PuzzlePiece,
  ShieldCheck,
  Sparkle,
} from "@phosphor-icons/react";
import { useHostTRPC } from "@posthog/host-router/react";
import { happyHog } from "@posthog/ui/assets/hedgehogs";
import { StepActions } from "@posthog/ui/features/onboarding/components/StepActions";
import { OnboardingHogTip } from "@posthog/ui/primitives/OnboardingHogTip";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import { Button, Flex, Spinner, Text } from "@radix-ui/themes";
import { useQuery } from "@tanstack/react-query";
import { motion } from "framer-motion";
import { useEffect, useState } from "react";
import "./ImportConfigStep.css";

interface ImportConfigStepProps {
  onNext: () => void;
  onBack: () => void;
}

interface StatCard {
  key: string;
  label: string;
  count: number;
  paths: string[];
  icon: Icon;
}

function PathChip({ paths }: { paths: string[] }) {
  const [primary, ...rest] = paths ?? [];
  if (!primary) return null;

  const chip = (
    <span className="import-stat-card__path">
      <Folder size={11} weight="duotone" />
      <span className="import-stat-card__path-text">{primary}</span>
      {rest.length > 0 && (
        <span className="import-stat-card__path-more">+{rest.length}</span>
      )}
    </span>
  );

  if (rest.length === 0) return chip;

  return (
    <Tooltip
      side="bottom"
      content={
        <Flex direction="column" gap="1">
          {paths.map((p) => (
            <span key={p} className="font-[var(--code-font-family)] text-xs">
              {p}
            </span>
          ))}
        </Flex>
      }
    >
      {chip}
    </Tooltip>
  );
}

const prefersReducedMotion = () =>
  window?.matchMedia("(prefers-reduced-motion: reduce)").matches;

function useCountUp(target: number, durationMs = 850, delayMs = 0): number {
  const [value, setValue] = useState(() =>
    prefersReducedMotion() ? target : 0,
  );

  useEffect(() => {
    if (prefersReducedMotion() || target === 0) {
      setValue(target);
      return;
    }
    let raf = 0;
    let startTs = 0;
    const step = (now: number) => {
      if (!startTs) startTs = now;
      const t = Math.min(1, (now - startTs) / durationMs);
      const eased = 1 - (1 - t) ** 3;
      setValue(Math.round(eased * target));
      if (t < 1) raf = requestAnimationFrame(step);
    };
    const timer = setTimeout(() => {
      raf = requestAnimationFrame(step);
    }, delayMs);
    return () => {
      clearTimeout(timer);
      cancelAnimationFrame(raf);
    };
  }, [target, durationMs, delayMs]);

  return value;
}

function StatCardView({ card, index }: { card: StatCard; index: number }) {
  const IconComponent = card.icon;
  const isEmpty = card.count === 0;
  const entryDelay = 0.06 + index * 0.07;
  const count = useCountUp(card.count, 850, (entryDelay + 0.18) * 1000);

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{
        duration: 0.35,
        delay: entryDelay,
        ease: [0.16, 1, 0.3, 1],
      }}
      className={
        isEmpty
          ? "import-stat-card import-stat-card--empty"
          : "import-stat-card"
      }
    >
      <div className="import-stat-card__grid" aria-hidden="true" />
      <div className="import-stat-card__glow" aria-hidden="true" />
      <Flex direction="column" gap="3" className="relative z-10">
        <span className="import-stat-card__icon">
          <IconComponent size={17} weight="duotone" />
        </span>
        <Flex direction="column" gap="2">
          <Flex align="baseline" gap="2" wrap="wrap">
            <span className="import-stat-card__count">{count}</span>
            <Text className="font-semibold text-(--gray-12) text-base leading-tight">
              {card.label}
            </Text>
          </Flex>
          <PathChip paths={card.paths} />
        </Flex>
      </Flex>
    </motion.div>
  );
}

export function ImportConfigStep({ onNext, onBack }: ImportConfigStepProps) {
  const trpc = useHostTRPC();
  const { data: summary, isLoading } = useQuery(
    trpc.onboardingImport.getSummary.queryOptions(undefined, {
      staleTime: 60_000,
    }),
  );

  const cards: StatCard[] = summary
    ? [
        {
          key: "skills",
          label: summary.skills.count === 1 ? "Skill" : "Skills",
          count: summary.skills.count,
          paths: summary.skills.paths,
          icon: Sparkle,
        },
        {
          key: "plugins",
          label: summary.plugins.count === 1 ? "Plugin" : "Plugins",
          count: summary.plugins.count,
          paths: summary.plugins.paths,
          icon: PuzzlePiece,
        },
        {
          key: "mcp",
          label: summary.mcpServers.count === 1 ? "MCP server" : "MCP servers",
          count: summary.mcpServers.count,
          paths: summary.mcpServers.paths,
          icon: PlugsConnected,
        },
        {
          key: "permissions",
          label: "Permission rules",
          count: summary.permissions.count,
          paths: summary.permissions.paths,
          icon: ShieldCheck,
        },
      ]
    : [];

  return (
    <Flex align="center" height="100%" px="8">
      <Flex
        direction="column"
        align="center"
        className="h-full w-full pt-[24px] pb-[40px]"
      >
        <Flex direction="column" className="min-h-0 flex-1 overflow-y-auto">
          <Flex
            direction="column"
            gap="5"
            className="m-auto w-full max-w-[560px]"
          >
            <motion.div
              initial={{ opacity: 0, y: 8 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.3 }}
            >
              <Flex direction="column" gap="2">
                <Text className="font-bold text-(--gray-12) text-2xl tracking-[-0.02em]">
                  Your Claude Code environment is ready
                </Text>
                <Text className="text-(--gray-11) text-sm leading-relaxed">
                  Same workflow, now in PostHog.
                </Text>
              </Flex>
            </motion.div>

            {isLoading ? (
              <Flex align="center" justify="center" className="py-12">
                <Spinner size="3" />
              </Flex>
            ) : (
              <>
                <div className="grid w-full grid-cols-2 gap-3">
                  {cards.map((card, index) => (
                    <StatCardView key={card.key} card={card} index={index} />
                  ))}
                </div>
                <OnboardingHogTip
                  hogSrc={happyHog}
                  message="All your favorite skills, plugins, and MCP servers are ready to use."
                  delay={0.2 + cards.length * 0.07}
                />
              </>
            )}
          </Flex>
        </Flex>

        <StepActions>
          <Button size="3" variant="outline" color="gray" onClick={onBack}>
            <ArrowLeft size={16} weight="bold" />
            Back
          </Button>
          <Button size="3" onClick={onNext}>
            Continue
            <ArrowRight size={16} weight="bold" />
          </Button>
        </StepActions>
      </Flex>
    </Flex>
  );
}
