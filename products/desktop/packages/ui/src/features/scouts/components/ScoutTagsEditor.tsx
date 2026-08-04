import { XIcon } from "@phosphor-icons/react";
import type { ScoutConfig } from "@posthog/api-client/posthog-client";
import {
  MAX_SCOUT_TAG_LENGTH,
  MAX_SCOUT_TAGS,
  parseScoutTagsInput,
  scoutTags,
  withScoutTagRemoved,
  withScoutTagsAdded,
} from "@posthog/core/scouts/scoutTags";
import { Flex, Text } from "@radix-ui/themes";
import { useState } from "react";
import type { ScoutConfigUpdate } from "../hooks/useScoutConfigMutations";
import { ScoutTagBadge } from "./ScoutBadges";

/**
 * Chips-plus-input tag editor for one scout, rendered inside the settings form
 * so both the fleet row's gear and the detail header get it. Each add or remove
 * is its own PATCH of the whole tag set — there is no save button, matching how
 * the mode and cadence selects in the same form commit immediately.
 */
export function ScoutTagsEditor({
  config,
  onUpdate,
}: {
  config: ScoutConfig;
  onUpdate: (configId: string, updates: ScoutConfigUpdate) => void;
}) {
  const [draft, setDraft] = useState("");
  const [tooLong, setTooLong] = useState(false);
  const tags = scoutTags(config);
  const atCap = tags.length >= MAX_SCOUT_TAGS;

  // `withScoutTags*` return null when the edit is a no-op, so a stray blur or a
  // re-typed tag never fires a PATCH that changes nothing.
  const commitDraft = () => {
    const parsed = parseScoutTagsInput(draft);
    setTooLong(parsed.tooLong.length > 0);
    // Keep the draft when something was too long so it can be shortened in
    // place; the server would reject it anyway, one round trip later.
    if (parsed.tooLong.length > 0) return;
    const next = withScoutTagsAdded(tags, parsed.tags);
    setDraft("");
    if (next) onUpdate(config.id, { tags: next });
  };

  const removeTag = (tag: string) => {
    const next = withScoutTagRemoved(tags, tag);
    if (next) onUpdate(config.id, { tags: next });
  };

  return (
    <Flex direction="column" gap="1">
      <Flex align="center" gap="1" wrap="wrap">
        {tags.map((tag) => (
          <ScoutTagBadge key={tag} tag={tag}>
            <button
              type="button"
              onClick={() => removeTag(tag)}
              aria-label={`Remove tag ${tag} from ${config.skill_name}`}
              className="-mr-0.5 flex items-center text-(--iris-11) opacity-60 transition-opacity hover:opacity-100"
            >
              <XIcon size={9} weight="bold" />
            </button>
          </ScoutTagBadge>
        ))}
        <input
          value={draft}
          onChange={(event) => {
            setDraft(event.target.value);
            setTooLong(false);
          }}
          onBlur={commitDraft}
          onKeyDown={(event) => {
            if (event.key === "Enter" || event.key === ",") {
              event.preventDefault();
              commitDraft();
            } else if (
              event.key === "Backspace" &&
              draft === "" &&
              tags.length > 0
            ) {
              // Backspace on an empty input peels the last chip, the convention
              // every other chips input follows.
              event.preventDefault();
              removeTag(tags[tags.length - 1]);
            }
          }}
          disabled={atCap}
          placeholder={atCap ? `${MAX_SCOUT_TAGS} tag limit` : "Add tag…"}
          aria-label={`${config.skill_name} tags`}
          className="h-5 w-24 min-w-0 rounded border border-transparent bg-transparent px-1 text-[11.5px] text-gray-12 placeholder:text-gray-9 hover:border-(--gray-6) focus:border-(--gray-7) focus:outline-none disabled:cursor-default"
        />
      </Flex>
      {tooLong ? (
        <Text className="text-(--red-11) text-[11.5px]">
          Tags are capped at {MAX_SCOUT_TAG_LENGTH} characters.
        </Text>
      ) : null}
    </Flex>
  );
}
