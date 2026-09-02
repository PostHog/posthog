import {
  getPrVisualConfig,
  type PrVisualConfig,
} from "@posthog/core/git-interaction/prStatus";
import { Text } from "react-native";
import { usePrStatus } from "@/features/tasks/hooks/usePrStatus";
import { openExternalUrl } from "@/lib/openExternalUrl";
import {
  MERGED_COLOR,
  type ThemeColors,
  toRgba,
  useThemeColors,
} from "@/lib/theme";

interface GithubRefChipProps {
  href: string;
  kind: "issue" | "pr";
  label: string;
}

function toneColor(color: PrVisualConfig["color"], theme: ThemeColors): string {
  switch (color) {
    case "green":
      return theme.status.success;
    case "red":
      return theme.status.error;
    case "purple":
      return MERGED_COLOR;
    default:
      return theme.gray[11];
  }
}

// Rendered as a plain <Text> so it can be embedded inline within markdown
// paragraphs (RN does not allow <View> children inside <Text>). The icon
// from the desktop chip is omitted for the same reason — visual distinction
// comes from the chip background + monospace + accent color.
export function GithubRefChip({ href, kind, label }: GithubRefChipProps) {
  if (kind === "pr") {
    return <GithubPrRefChip href={href} label={label} />;
  }
  return (
    <RefChip
      href={href}
      label={label}
      accessibilityLabel={`GitHub issue ${label}`}
    />
  );
}

// The PR's live lifecycle drives the chip's tint and its accessibility label,
// since a phone has no hover card to carry the state. Unknown status (still
// loading, private repo, or a failed request) falls back to the neutral chip.
function GithubPrRefChip({ href, label }: { href: string; label: string }) {
  const { data: status } = usePrStatus(href);
  const themeColors = useThemeColors();

  const config = status
    ? getPrVisualConfig(status.state, status.merged, status.draft)
    : undefined;
  return (
    <RefChip
      href={href}
      label={label}
      accessibilityLabel={
        config
          ? `GitHub pull request ${label}, ${config.label.toLowerCase()}`
          : `GitHub pull request ${label}`
      }
      color={config ? toneColor(config.color, themeColors) : undefined}
    />
  );
}

function RefChip({
  href,
  label,
  accessibilityLabel,
  color,
}: {
  href: string;
  label: string;
  accessibilityLabel: string;
  color?: string;
}) {
  return (
    <Text
      onPress={() => openExternalUrl(href)}
      className="rounded-md bg-gray-3 px-1.5 py-0.5 font-mono text-[11px] text-accent-11"
      style={
        color ? { backgroundColor: toRgba(color, 0.12), color } : undefined
      }
      accessibilityRole="link"
      accessibilityLabel={accessibilityLabel}
    >
      {label}
    </Text>
  );
}
