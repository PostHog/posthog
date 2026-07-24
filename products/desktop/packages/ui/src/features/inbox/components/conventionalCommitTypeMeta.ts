import type { Icon } from "@phosphor-icons/react";
import {
  ArrowCounterClockwiseIcon,
  ArrowsClockwiseIcon,
  BookOpenIcon,
  BroomIcon,
  FlaskIcon,
  LightningIcon,
  PackageIcon,
  PaintBrushIcon,
  PlayCircleIcon,
  QuestionIcon,
  SparkleIcon,
  WrenchIcon,
} from "@phosphor-icons/react";
import type { badgeVariants } from "@posthog/quill";
import type { VariantProps } from "class-variance-authority";

type ConventionalCommitBadgeVariant = NonNullable<
  VariantProps<typeof badgeVariants>["variant"]
>;

export interface ConventionalCommitTypeMeta {
  icon: Icon;
  variant: ConventionalCommitBadgeVariant;
  softIconClass: string;
}

const TYPE_META: Record<string, ConventionalCommitTypeMeta> = {
  feat: {
    icon: SparkleIcon,
    variant: "success",
    softIconClass: "text-(--green-10)",
  },
  fix: { icon: WrenchIcon, variant: "info", softIconClass: "text-(--blue-10)" },
  docs: {
    icon: BookOpenIcon,
    variant: "info",
    softIconClass: "text-(--blue-10)",
  },
  style: {
    icon: PaintBrushIcon,
    variant: "default",
    softIconClass: "text-gray-10",
  },
  refactor: {
    icon: ArrowsClockwiseIcon,
    variant: "warning",
    softIconClass: "text-(--amber-10)",
  },
  test: { icon: FlaskIcon, variant: "info", softIconClass: "text-(--blue-10)" },
  chore: {
    icon: BroomIcon,
    variant: "default",
    softIconClass: "text-gray-10",
  },
  build: {
    icon: PackageIcon,
    variant: "default",
    softIconClass: "text-gray-10",
  },
  ci: {
    icon: PlayCircleIcon,
    variant: "info",
    softIconClass: "text-(--blue-10)",
  },
  perf: {
    icon: LightningIcon,
    variant: "warning",
    softIconClass: "text-(--amber-10)",
  },
  revert: {
    icon: ArrowCounterClockwiseIcon,
    variant: "default",
    softIconClass: "text-gray-10",
  },
};

const DEFAULT_META: ConventionalCommitTypeMeta = {
  icon: QuestionIcon,
  variant: "default",
  softIconClass: "text-gray-10",
};

export function getConventionalCommitTypeMeta(
  type: string,
): ConventionalCommitTypeMeta {
  return TYPE_META[type] ?? DEFAULT_META;
}

export function formatConventionalCommitTag(
  type: string,
  scope: string | null,
): string {
  return scope ? `${type}(${scope})` : type;
}
