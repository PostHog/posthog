import { mergePrUrls } from "@posthog/shared";

/**
 * Pull requests attached to a ticket by hand, stored as tags because
 * Conversations has no field for them. The separator is a slash: some systems
 * a ticket's tags pass through strip a hash, so `pr:owner/repo/123` survives
 * where `pr:owner/repo#123` does not. The hash form is still read, since
 * tickets carry it from before the change.
 */
const PR_TAG_PREFIX = "pr:";

const PR_TAG_PATTERN = /^([^/\s]+)\/([^/#\s]+)[/#](\d+)$/;

export function ticketPrUrlFromTag(tag: string): string | null {
  if (!tag.toLowerCase().startsWith(PR_TAG_PREFIX)) {
    return null;
  }

  const match = PR_TAG_PATTERN.exec(tag.slice(PR_TAG_PREFIX.length).trim());
  if (!match) {
    return null;
  }

  const [, owner, repo, number] = match;
  return `https://github.com/${owner}/${repo}/pull/${number}`;
}

/** The pull requests a person attached to this ticket, in tag order. */
export function readTicketPrUrls(
  tags: readonly string[] | undefined,
): string[] {
  const urls: string[] = [];
  for (const tag of tags ?? []) {
    const url = ticketPrUrlFromTag(tag);
    if (url && !urls.includes(url)) {
      urls.push(url);
    }
  }
  return urls;
}

/**
 * Everything a ticket points at: what a person attached, then what its agent
 * thread opened.
 *
 * The thread's pull requests are read from the task on every render rather than
 * copied onto the ticket, so the task stays the one record of what the agent
 * did. Attached ones come first because someone chose them.
 */
export function resolveTicketPrUrls(
  tags: readonly string[] | undefined,
  taskPrUrls: readonly string[],
): string[] {
  return mergePrUrls(readTicketPrUrls(tags), taskPrUrls);
}
