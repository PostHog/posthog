import { Text } from "@components/text";
import {
  ArrowCounterClockwise,
  ArrowsClockwise,
  BookOpen,
  Broom,
  Flask,
  type Icon,
  Lightning,
  Package,
  PaintBrush,
  PlayCircle,
  Question,
  Sparkle,
  Wrench,
} from "phosphor-react-native";
import { View } from "react-native";
import { type ThemeColors, useThemeColors } from "@/lib/theme";

type TagColor = "green" | "blue" | "amber" | "gray";

interface TypeMeta {
  icon: Icon;
  color: TagColor;
}

const TYPE_META: Record<string, TypeMeta> = {
  feat: { icon: Sparkle, color: "green" },
  fix: { icon: Wrench, color: "blue" },
  docs: { icon: BookOpen, color: "blue" },
  style: { icon: PaintBrush, color: "gray" },
  refactor: { icon: ArrowsClockwise, color: "amber" },
  test: { icon: Flask, color: "blue" },
  chore: { icon: Broom, color: "gray" },
  build: { icon: Package, color: "gray" },
  ci: { icon: PlayCircle, color: "blue" },
  perf: { icon: Lightning, color: "amber" },
  revert: { icon: ArrowCounterClockwise, color: "gray" },
};

const DEFAULT_META: TypeMeta = { icon: Question, color: "gray" };

const COLOR_RESOLVERS: Record<TagColor, (t: ThemeColors) => string> = {
  green: (t) => t.status.success,
  blue: (t) => t.status.info,
  amber: (t) => t.status.warning,
  gray: (t) => t.gray[10],
};

interface ConventionalCommitTagProps {
  type: string;
  scope: string | null;
}

export function ConventionalCommitTag({
  type,
  scope,
}: ConventionalCommitTagProps) {
  const themeColors = useThemeColors();
  const meta = TYPE_META[type] ?? DEFAULT_META;
  const IconCmp = meta.icon;
  const label = scope ? `${type}(${scope})` : type;
  const iconColor = COLOR_RESOLVERS[meta.color](themeColors);

  return (
    <View className="shrink-0 flex-row items-center gap-1 rounded border border-gray-6 bg-gray-2 px-1.5 py-0.5">
      <IconCmp size={10} color={iconColor} weight="bold" />
      <Text className="font-mono text-[11px] text-gray-11">{label}</Text>
    </View>
  );
}
