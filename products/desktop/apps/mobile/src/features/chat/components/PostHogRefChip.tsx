import { Text } from "react-native";
import { openExternalUrl } from "@/lib/openExternalUrl";
import type { PostHogRefKind } from "@/lib/posthogUrl";

interface PostHogRefChipProps {
  href: string;
  kind: PostHogRefKind;
  label: string;
}

export function PostHogRefChip({ href, kind, label }: PostHogRefChipProps) {
  const destination =
    kind === "docs"
      ? "docs"
      : kind === "code"
        ? "Code"
        : kind === "website"
          ? "website"
          : "app";

  return (
    <Text
      onPress={() => openExternalUrl(href)}
      className="rounded-md bg-gray-3 px-1.5 py-0.5 font-mono text-[11px] text-accent-11"
      accessibilityRole="link"
      accessibilityLabel={`PostHog ${destination} link ${label}`}
    >
      {label}
    </Text>
  );
}
