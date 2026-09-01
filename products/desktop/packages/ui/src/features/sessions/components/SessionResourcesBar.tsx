import type { IconProps } from "@phosphor-icons/react";
import {
  BrainIcon,
  BugIcon,
  ChartLineIcon,
  ClipboardTextIcon,
  DatabaseIcon,
  FileTextIcon,
  FlagIcon,
  FlaskIcon,
  GaugeIcon,
  GlobeIcon,
  PlugIcon,
  SparkleIcon,
  TableIcon,
  VideoIcon,
} from "@phosphor-icons/react";
import type { PostHogProductId } from "@posthog/agent/posthog-products";
import type { AcpMessage } from "@posthog/shared";
import { CHAT_CONTENT_MAX_WIDTH } from "@posthog/ui/features/sessions/constants";
import { openUrlInBrowser } from "@posthog/ui/utils/browser";
import { Badge, Box, Flex, Text } from "@radix-ui/themes";
import { type ComponentType, useMemo, useRef, useState } from "react";
import { createSessionResourcesTracker } from "./accumulateSessionResources";

/**
 * Icon per PostHog product. `Record<PostHogProductId, …>` keeps this exhaustive:
 * adding a product id in `@posthog/agent` forces an icon here at compile time.
 */
const PRODUCT_ICON: Record<PostHogProductId, ComponentType<IconProps>> = {
  product_analytics: ChartLineIcon,
  web_analytics: GlobeIcon,
  feature_flags: FlagIcon,
  experiments: FlaskIcon,
  error_tracking: BugIcon,
  session_replay: VideoIcon,
  surveys: ClipboardTextIcon,
  llm_analytics: BrainIcon,
  data_warehouse: DatabaseIcon,
  cdp: PlugIcon,
  logs: FileTextIcon,
  apm: GaugeIcon,
  sql: TableIcon,
};

/**
 * Docs page on posthog.com per product, so a chip links to the relevant
 * product docs. `Partial` on purpose — products without a dedicated docs page
 * (e.g. apm, which PostHog folds into LLM analytics / Logs) render as a plain,
 * non-clickable badge rather than linking somewhere misleading.
 */
const PRODUCT_DOC_URL: Partial<Record<PostHogProductId, string>> = {
  product_analytics: "https://posthog.com/docs/product-analytics",
  web_analytics: "https://posthog.com/docs/web-analytics",
  feature_flags: "https://posthog.com/docs/feature-flags",
  experiments: "https://posthog.com/docs/experiments",
  error_tracking: "https://posthog.com/docs/error-tracking",
  session_replay: "https://posthog.com/docs/session-replay",
  surveys: "https://posthog.com/docs/surveys",
  llm_analytics: "https://posthog.com/docs/ai-observability",
  data_warehouse: "https://posthog.com/docs/data-warehouse",
  cdp: "https://posthog.com/docs/cdp",
  logs: "https://posthog.com/docs/logs",
  sql: "https://posthog.com/docs/sql",
};

interface SessionResourcesBarProps {
  events: AcpMessage[];
}

/**
 * How many chips to show before collapsing the rest behind a "+N" badge.
 * Keeps the bar to a single tidy row in the common case; the user can expand
 * to reveal everything when the agent has touched a lot of products.
 */
const MAX_VISIBLE_CHIPS = 6;

/**
 * Persistent bar above the composer listing the PostHog products the agent has
 * touched so far this session — via the MCP `exec` tool, or by reading a file
 * from the codebase (the "Code" chip). Each product appears once and is added
 * the moment it's first used. Hidden until at least one product has been used.
 * Mirrors PlanStatusBar's placement and styling.
 */
export function SessionResourcesBar({ events }: SessionResourcesBarProps) {
  const trackerRef = useRef<ReturnType<
    typeof createSessionResourcesTracker
  > | null>(null);
  trackerRef.current ??= createSessionResourcesTracker();
  const tracker = trackerRef.current;
  const products = useMemo(() => tracker.update(events), [events, tracker]);
  const [expanded, setExpanded] = useState(false);

  if (products.length === 0) return null;

  const overflowCount = products.length - MAX_VISIBLE_CHIPS;
  const hasOverflow = overflowCount > 0;
  const visibleProducts =
    hasOverflow && !expanded ? products.slice(0, MAX_VISIBLE_CHIPS) : products;

  return (
    <Box className="mb-3">
      <Box className="mx-auto" style={{ maxWidth: CHAT_CONTENT_MAX_WIDTH }}>
        <Flex
          align="center"
          gap="1"
          wrap="wrap"
          className="overflow-hidden px-3 pt-2"
        >
          <Text color="gray" className="whitespace-nowrap text-[11px]">
            PostHog resources used
          </Text>
          {visibleProducts.map((product) => {
            const Icon = PRODUCT_ICON[product.id] ?? SparkleIcon;
            const docUrl = PRODUCT_DOC_URL[product.id];
            return (
              <Badge
                key={product.id}
                size="1"
                color="gray"
                variant="soft"
                className={
                  docUrl
                    ? "max-w-full cursor-pointer text-[11px] hover:bg-gray-4"
                    : "max-w-full text-[11px]"
                }
                onClick={
                  docUrl ? () => void openUrlInBrowser(docUrl) : undefined
                }
                title={docUrl ? `Open ${product.label} docs` : undefined}
              >
                <Icon size={11} className="shrink-0" />
                <span className="truncate">{product.label}</span>
              </Badge>
            );
          })}
          {hasOverflow && (
            <Badge
              size="1"
              color="gray"
              variant="soft"
              className="cursor-pointer text-[11px] hover:bg-gray-4"
              onClick={() => setExpanded((prev) => !prev)}
              title={expanded ? "Show fewer" : "Show all resources used"}
            >
              {expanded ? "Show less" : `+${overflowCount} more`}
            </Badge>
          )}
        </Flex>
      </Box>
    </Box>
  );
}
