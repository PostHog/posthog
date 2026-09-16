import {
  FigmaLogoIcon,
  GitlabLogoIcon,
  type Icon,
  NotionLogoIcon,
  PlugsIcon,
} from "@phosphor-icons/react";
import type { ContextSource } from "@posthog/core/canvas/contextSources";
import { ServerIcon } from "@posthog/ui/features/mcp-servers/components/parts/icons";
import { SlackMark } from "@posthog/ui/primitives/SlackMark";

// Sources with a brand glyph. Slack gets its four-colour mark because the
// monochrome one reads as a globe at row size. The rest fall back to a plug.
const BRAND_GLYPHS: Record<string, Icon> = {
  slack: SlackMark,
  notion: NotionLogoIcon,
  figma: FigmaLogoIcon,
  gitlab: GitlabLogoIcon,
};

/**
 * A source's logo: the brand image from the icon proxy when it has one, and
 * the brand glyph while it loads or when the proxy has no image, so a Slack
 * link never shows as a blank square.
 */
export function SourceLogo({
  source,
  size = 16,
}: {
  source: Pick<ContextSource, "id" | "iconDomain">;
  size?: number;
}) {
  const Glyph = BRAND_GLYPHS[source.id] ?? PlugsIcon;
  return (
    <ServerIcon
      iconDomain={source.iconDomain}
      size={size}
      fallback={<Glyph size={size} className="text-foreground" />}
    />
  );
}
