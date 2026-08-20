export const PERSONAL_CHANNEL_NAME = "me";

export const GENERAL_CHANNEL_NAME = "general";

export interface ChannelIdentity {
  system_role?: "personal" | "general" | null;
  channel_type: "public" | "personal";
  name: string;
}

export function isPersonalChannel(channel: ChannelIdentity): boolean {
  return channel.system_role != null
    ? channel.system_role === "personal"
    : channel.channel_type === "personal";
}

export function isGeneralChannel(channel: ChannelIdentity): boolean {
  return channel.system_role != null
    ? channel.system_role === "general"
    : channel.channel_type === "public" &&
        channel.name === GENERAL_CHANNEL_NAME;
}

/**
 * What that channel is called on screen.
 *
 * Renaming the row itself would rewrite every existing channel and any link
 * that names one, so the swap happens on the way to a reader. Lowercase, like
 * every other space's name: the sidebar is a column of names the backend
 * normalized, and one capitalized row reads as a different kind of thing.
 *
 * Lives in core because names reach a reader by more routes than the channel
 * list — an activity row and a mention both carry one of their own.
 */
export const PERSONAL_CHANNEL_LABEL = "personal";

/** A channel's name as a reader should see it. */
export function channelDisplayName(name: string): string;
export function channelDisplayName(name: string | null): string | null;
export function channelDisplayName(name: string | null): string | null {
  return name === PERSONAL_CHANNEL_NAME ? PERSONAL_CHANNEL_LABEL : name;
}

function isPersonalChannelLabel(
  name: string,
  channelType?: "public" | "personal",
): boolean {
  return channelType !== undefined
    ? channelType === "personal"
    : name === PERSONAL_CHANNEL_NAME || name === PERSONAL_CHANNEL_LABEL;
}

export function channelDisplayLabel(
  name: string,
  channelType?: "public" | "personal",
): string {
  return isPersonalChannelLabel(name, channelType)
    ? PERSONAL_CHANNEL_LABEL
    : `#${channelDisplayName(name)}`;
}

export function channelDisplayReference(
  name: string,
  channelType?: "public" | "personal",
): string {
  return isPersonalChannelLabel(name, channelType)
    ? "your personal space"
    : `#${channelDisplayName(name)}`;
}

// The server normalizes a name to this shape (`normalize_channel_name`), so anything
// else would be stored as something other than what the field showed.
export const CHANNEL_NAME_PATTERN = /^[a-z0-9-]+$/;

function replaceChannelNameSeparators(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "-");
}

export function normalizeChannelNameInput(name: string): string {
  return replaceChannelNameSeparators(name).replace(/^-+/, "");
}

export function normalizeChannelName(name: string): string {
  return normalizeChannelNameInput(name).replace(/-+$/, "");
}

// Returns an error message for an invalid name, or null when valid. Empty is
// treated as valid here — callers already gate on a non-empty trimmed value, so
// this validator only judges the character set.
/**
 * Names a space can't take, because the private space already answers to them
 * and a second space wearing one is a space pretending to be yours.
 *
 * Client-side only, so it stops the two forms that create and rename spaces —
 * not the API, and not a space that took the name before this landed.
 */
const RESERVED_CHANNEL_NAMES = new Set([
  PERSONAL_CHANNEL_NAME,
  PERSONAL_CHANNEL_LABEL,
]);

export function validateChannelName(name: string): string | null {
  const trimmed = name.trim();
  if (!trimmed) return null;
  if (!CHANNEL_NAME_PATTERN.test(trimmed)) {
    return "Use only lowercase letters, numbers, and hyphens.";
  }
  if (RESERVED_CHANNEL_NAMES.has(trimmed.toLowerCase())) {
    return `"${trimmed}" is reserved for your private space.`;
  }
  return null;
}
