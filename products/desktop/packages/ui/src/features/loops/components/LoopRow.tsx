import { CaretRightIcon, RepeatIcon } from "@phosphor-icons/react";
import type { LoopSchemas } from "@posthog/api-client/loops";
import { formatRelativeTimeLong } from "@posthog/shared";
import type { UserBasic } from "@posthog/shared/domain-types";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";
import { Badge } from "@posthog/ui/primitives/Badge";
import { Flex, Text } from "@radix-ui/themes";
import { Link } from "@tanstack/react-router";
import {
  loopStatusColor,
  loopStatusLabel,
  summarizeNotificationDestinations,
} from "../loopDisplay";

export function LoopRow({
  loop,
  creator,
  creatorLoading = false,
  creatorError = false,
  creatorLookupComplete = true,
}: {
  loop: LoopSchemas.Loop;
  creator?: UserBasic;
  creatorLoading?: boolean;
  creatorError?: boolean;
  creatorLookupComplete?: boolean;
}) {
  const description = loop.description.trim();

  let creatorLabel: string | null = null;
  if (loop.visibility === "team" && creatorError) {
    creatorLabel = "Creator unavailable";
  } else if (
    loop.visibility === "team" &&
    !creatorLoading &&
    !creatorLookupComplete
  ) {
    creatorLabel = "Creator unavailable";
  } else if (loop.visibility === "team" && !creatorLoading) {
    creatorLabel = creator
      ? `Created by ${userDisplayName(creator)}`
      : "Created by a former organization member";
  }

  const metadata: string[] = [];
  const notificationDestinations = summarizeNotificationDestinations(
    loop.notifications,
  );
  if (notificationDestinations.length > 0) {
    metadata.push(`Notifications: ${notificationDestinations.join(", ")}`);
  }
  if (creatorLabel) metadata.push(creatorLabel);

  return (
    <Link
      to="/code/loops/$loopId"
      params={{ loopId: loop.id }}
      className="flex items-center justify-between gap-3 rounded-(--radius-2) border border-border bg-(--color-panel-solid) px-4 py-3.5 no-underline transition-colors duration-150 hover:border-(--gray-6) hover:bg-(--gray-2)"
    >
      <Flex align="center" gap="3" className="min-w-0">
        <RepeatIcon size={20} className="shrink-0 text-gray-11" />
        <Flex direction="column" gap="1" className="min-w-0">
          <Flex align="center" gap="2" className="min-w-0">
            <Text className="truncate font-medium text-[13px] text-gray-12">
              {loop.name}
            </Text>
            <Badge color={loopStatusColor(loop)}>{loopStatusLabel(loop)}</Badge>
            <Badge color="gray">{loop.visibility}</Badge>
          </Flex>
          {description ? (
            <Text className="truncate text-[12px] text-gray-11 leading-snug">
              {description}
            </Text>
          ) : null}
          <Flex align="center" gap="1" wrap="wrap" className="mt-0.5">
            {metadata.length > 0 ? (
              <Text className="text-(--accent-11) text-[11px] leading-snug">
                {metadata.join(" · ")}
              </Text>
            ) : null}
            {metadata.length > 0 ? (
              <Text className="text-[11px] text-gray-9">·</Text>
            ) : null}
            <Text className="text-[11px] text-gray-9">
              Created {formatRelativeTimeLong(loop.created_at)}
            </Text>
          </Flex>
        </Flex>
      </Flex>
      <Flex align="center" gap="3" className="shrink-0">
        {loop.consecutive_failures > 0 ? (
          <Text className="text-(--red-11) text-[11px]">
            {loop.consecutive_failures} failed in a row
          </Text>
        ) : null}
        <CaretRightIcon size={14} className="shrink-0 text-gray-10" />
      </Flex>
    </Link>
  );
}
