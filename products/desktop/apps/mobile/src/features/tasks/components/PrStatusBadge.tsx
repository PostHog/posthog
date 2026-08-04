import { GitMerge, GitPullRequest } from "phosphor-react-native";
import { Pressable } from "react-native";
import { openExternalUrl } from "@/lib/openExternalUrl";
import { toRgba, useThemeColors } from "@/lib/theme";
import { usePrStatus } from "../hooks/usePrStatus";

interface PrStatusBadgeProps {
  prUrl: string;
  // Render nothing until the PR state resolves, and only for a canonical
  // GitHub PR URL. Inbox surfaces use this so an always-on neutral icon never
  // implies a status we couldn't confirm (private repo, 404, unparseable URL).
  hideWhenUnresolved?: boolean;
  size?: "sm" | "md";
}

// Mirrors the desktop "merged" PR color (Radix purple-9 family). Theme tokens
// don't include a purple, and merged-PR purple is recognisable enough that a
// fixed value works in both light and dark.
const MERGED_COLOR = "#8e4ec6";

export function PrStatusBadge({
  prUrl,
  hideWhenUnresolved = false,
  size = "md",
}: PrStatusBadgeProps) {
  const themeColors = useThemeColors();
  const { data: status } = usePrStatus(prUrl);

  if (hideWhenUnresolved && !status) return null;

  const handlePress = () => {
    openExternalUrl(prUrl);
  };

  let color: string = themeColors.gray[11];
  let Icon: typeof GitPullRequest = GitPullRequest;
  let label = "Open PR";

  if (status?.merged) {
    color = MERGED_COLOR;
    Icon = GitMerge;
    label = "Open merged PR";
  } else if (status?.state === "closed") {
    color = themeColors.status.error;
    label = "Open closed PR";
  } else if (status?.draft) {
    color = themeColors.gray[11];
    label = "Open draft PR";
  } else if (status?.state === "open") {
    color = themeColors.status.success;
    label = "Open PR";
  }

  const box = size === "sm" ? "h-7 w-7" : "h-9 w-9";
  const iconSize = size === "sm" ? 16 : 20;

  return (
    <Pressable
      onPress={handlePress}
      hitSlop={10}
      className={`${box} items-center justify-center rounded-lg border active:opacity-60`}
      style={{
        backgroundColor: toRgba(color, 0.12),
        borderColor: toRgba(color, 0.35),
      }}
      accessibilityRole="link"
      accessibilityLabel={label}
    >
      <Icon size={iconSize} weight="bold" color={color} />
    </Pressable>
  );
}
