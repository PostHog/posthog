import { Text } from "react-native";
import { openExternalUrl } from "@/lib/openExternalUrl";

interface GithubRefChipProps {
  href: string;
  kind: "issue" | "pr";
  label: string;
}

// Rendered as a plain <Text> so it can be embedded inline within markdown
// paragraphs (RN does not allow <View> children inside <Text>). The icon
// from the desktop chip is omitted for the same reason — visual distinction
// comes from the chip background + monospace + accent color.
export function GithubRefChip({ href, kind, label }: GithubRefChipProps) {
  return (
    <Text
      onPress={() => openExternalUrl(href)}
      className="rounded-md bg-gray-3 px-1.5 py-0.5 font-mono text-[11px] text-accent-11"
      accessibilityRole="link"
      accessibilityLabel={`GitHub ${kind === "pr" ? "pull request" : "issue"} ${label}`}
    >
      {label}
    </Text>
  );
}
