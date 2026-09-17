import { PlugsIcon } from "@phosphor-icons/react";
import type { ContextSource } from "@posthog/core/canvas/contextSources";
import { ServerIcon } from "@posthog/ui/features/mcp-servers/components/parts/icons";
import { SlackMark } from "@posthog/ui/primitives/SlackMark";
import atlassianMark from "../../../../assets/services/atlassian.svg";
import boxMark from "../../../../assets/services/box.svg";
import figmaMark from "../../../../assets/services/figma.svg";
import gitlabMark from "../../../../assets/services/gitlab.svg";
import granolaMark from "../../../../assets/services/granola.png";
import hubspotMark from "../../../../assets/services/hubspot.png";
import linearMark from "../../../../assets/services/linear.svg";
import notionMark from "../../../../assets/services/notion.svg";
import sentryMark from "../../../../assets/services/sentry.svg";

// Every source ships its own brand mark, so a row never shows a stand-in
// glyph for a product it is not. Slack keeps its four-colour mark because the
// monochrome one reads as a globe at row size.
const BRAND_MARKS: Record<string, string> = {
  atlassian: atlassianMark,
  box: boxMark,
  figma: figmaMark,
  gitlab: gitlabMark,
  granola: granolaMark,
  hubspot: hubspotMark,
  linear: linearMark,
  notion: notionMark,
  sentry: sentryMark,
};

/**
 * A source's logo: the brand image from the icon proxy when it has one, and
 * the bundled brand mark while it loads or when the proxy has no image, so a
 * link never shows as a blank square or as another product's icon.
 */
export function SourceLogo({
  source,
  size = 16,
}: {
  source: Pick<ContextSource, "id" | "iconDomain">;
  size?: number;
}) {
  return (
    <ServerIcon
      iconDomain={source.iconDomain}
      size={size}
      fallback={<BrandMark id={source.id} size={size} />}
    />
  );
}

function BrandMark({ id, size }: { id: string; size: number }) {
  if (id === "slack")
    return <SlackMark size={size} className="text-foreground" />;
  const mark = BRAND_MARKS[id];
  if (!mark) return <PlugsIcon size={size} className="text-foreground" />;
  return (
    <img
      src={mark}
      alt=""
      width={size}
      height={size}
      className="size-full object-contain"
    />
  );
}
