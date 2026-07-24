import {
  Item,
  ItemContent,
  ItemDescription,
  ItemMedia,
  ItemTitle,
  Spinner,
} from "@posthog/quill";
import { getLocalDayDiff } from "@posthog/shared";
import type { TaskChannel } from "@posthog/shared/domain-types";
import { mentionChipClass } from "@posthog/ui/features/canvas/components/MentionText";
import { userDisplayName } from "@posthog/ui/features/canvas/utils/userDisplay";
import { Heading, Text } from "@radix-ui/themes";
import { FileCheckCorner, FilePlusCorner, Info } from "lucide-react";

// "today" / "yesterday" / "on July 10" for the intro's creation line.
function creationDatePhrase(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  const days = getLocalDayDiff(date);
  if (days <= 0) return "today";
  if (days === 1) return "yesterday";
  return `on ${date.toLocaleDateString(undefined, { month: "long", day: "numeric" })}`;
}

/** The intro card's lifecycle: unknown while the instructions query loads, a
 * create call to action, an in-flight plan session, or a published file. */
export type ContextMdState = "loading" | "none" | "building" | "created";

// The Slack-style intro pinned at the very start of a channel's feed: the
// channel name, who created it and when, and a context.md card that walks the
// create → building → created lifecycle. Derived entirely from the channel row,
// so it renders for every public channel, not just freshly created ones.
export function ChannelIntro({
  channel,
  channelName,
  contextMdState,
  onCreateContextMd,
}: {
  /** The backend channel row (creator + creation time). */
  channel: TaskChannel | undefined;
  channelName: string;
  contextMdState: ContextMdState;
  onCreateContextMd: () => void;
}) {
  const creator = channel?.created_by;

  return (
    <div className="flex w-full max-w-[70ch] flex-col gap-3 px-4 pt-8 pb-10">
      <div className="flex flex-col gap-0">
        <Heading className="font-bold text-2xl">{channelName}</Heading>
        {channel && (
          <Text size="2" className="text-muted-foreground">
            {/* Mention-styled but inert for now; later it opens the person. */}
            <span className={mentionChipClass}>
              @{userDisplayName(creator ?? null)}
            </span>{" "}
            created this channel {creationDatePhrase(channel.created_at)}. This
            is the very beginning of the{" "}
            <Text weight="bold">{channelName}</Text> channel.
          </Text>
        )}
      </div>
      <div className="flex gap-2">
        {contextMdState === "created" && (
          <Item className="w-full border-green-6 bg-green-2">
            <ItemMedia variant="icon">
              <FileCheckCorner size={18} />
            </ItemMedia>
            <ItemContent className="self-start">
              <ItemTitle>Created context.md</ItemTitle>
              <ItemDescription className="text-xs">
                Used in all sessions within this channel
              </ItemDescription>
            </ItemContent>
          </Item>
        )}
        {contextMdState === "building" && (
          <Item className="w-full border-blue-6 bg-blue-2">
            <ItemMedia variant="icon">
              <Spinner className="size-4" />
            </ItemMedia>
            <ItemContent className="self-start">
              <ItemTitle>Creating context.md</ItemTitle>
              <ItemDescription className="text-xs">
                A planning session is building it now. Open its task card below
                to shape the result.
              </ItemDescription>
            </ItemContent>
          </Item>
        )}
        {(contextMdState === "none" || contextMdState === "loading") && (
          <Item
            variant="pressable"
            className="w-full border-primary/50 bg-primary/10 hover:bg-primary/15"
            // While the instructions query resolves we don't yet know whether a
            // context.md exists; keep the layout stable but inert so a context
            // that has one never flashes an actionable "Create" state.
            render={
              <button
                type="button"
                disabled={contextMdState === "loading"}
                onClick={onCreateContextMd}
              />
            }
          >
            <ItemMedia variant="icon">
              <FilePlusCorner size={18} />
            </ItemMedia>
            <ItemContent className="self-start">
              <ItemTitle>Create a context.md</ItemTitle>
              <ItemDescription className="text-xs">
                Gives your agentic sessions everything they need to start new,
                or continue existing, tasks.
              </ItemDescription>
            </ItemContent>
          </Item>
        )}
        <Item
          className="w-full border-primary/50 hover:bg-fill-hover"
          variant="pressable"
          render={<button type="button" onClick={() => {}} />}
        >
          <ItemMedia variant="icon">
            <Info size={18} />
          </ItemMedia>
          <ItemContent className="self-start">
            <ItemTitle>Learn more about channels</ItemTitle>
            <ItemDescription className="text-xs">
              A channel is a group of tasks that are related to a specific
              topic.
            </ItemDescription>
          </ItemContent>
        </Item>
      </div>
    </div>
  );
}
