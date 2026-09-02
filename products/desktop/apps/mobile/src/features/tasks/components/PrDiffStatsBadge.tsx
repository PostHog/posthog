import { Text } from "@components/text";
import { useRouter } from "expo-router";
import { Pressable } from "react-native";
import { useThemeColors } from "@/lib/theme";
import { usePrStatus } from "../hooks/usePrStatus";

interface PrDiffStatsBadgeProps {
  prUrl: string;
}

function compact(n: number): string {
  if (n < 1000) return String(n);
  if (n < 10_000) return `${(n / 1000).toFixed(1).replace(/\.0$/, "")}k`;
  if (n < 1_000_000) return `${Math.round(n / 1000)}k`;
  return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
}

export function PrDiffStatsBadge({ prUrl }: PrDiffStatsBadgeProps) {
  const themeColors = useThemeColors();
  const router = useRouter();
  const { data } = usePrStatus(prUrl);

  // Hide while loading or when the GitHub API call failed (e.g. private repo
  // without auth). The PR status icon next door still tells the user a PR
  // exists; we just can't show the diff numbers.
  if (!data) return null;

  const handlePress = () => {
    router.push({ pathname: "/pr-diff", params: { prUrl } });
  };

  return (
    <Pressable
      onPress={handlePress}
      hitSlop={10}
      className="h-9 flex-row items-center gap-1 rounded-lg border border-gray-6 bg-gray-3 px-2.5 active:opacity-60"
      accessibilityRole="link"
      accessibilityLabel={`${data.additions} added, ${data.deletions} removed`}
    >
      <Text
        className="font-semibold text-[13px]"
        style={{ color: themeColors.status.success }}
      >
        +{compact(data.additions)}
      </Text>
      <Text
        className="font-semibold text-[13px]"
        style={{ color: themeColors.status.error }}
      >
        −{compact(data.deletions)}
      </Text>
    </Pressable>
  );
}
