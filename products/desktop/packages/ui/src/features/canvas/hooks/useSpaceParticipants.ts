import type { UserBasic } from "@posthog/shared/domain-types";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import { useMemo } from "react";

/** How far back a space is read for the people in it. */
const FETCH_LIMIT = 30;

/** Faces kept per space. Past this a row is a crowd, not an answer. */
const PARTICIPANTS_PER_SPACE = 12;

const NO_PEOPLE: UserBasic[] = [];

/**
 * Everyone who has worked in one space, most recently active first.
 *
 * Not presence: nobody ages out and nothing pulses. The question is whose
 * space this is, which does not change minute to minute, so this is fetched
 * once and left alone rather than polled.
 *
 * Per space rather than one project-wide page of recent tasks, because a page
 * ordered by activity across every space is the loudest few, and the quieter
 * ones come back empty — which reads as "nobody works here" for a space with
 * years of work in it. `enabled` is how a long list keeps that affordable: a
 * row asks only once it is on screen.
 */
export function useSpaceParticipants(
  channelId: string | undefined,
  { enabled = true }: { enabled?: boolean } = {},
): { people: UserBasic[]; isLoading: boolean } {
  const { data, isLoading } = useAuthenticatedQuery(
    ["space-participants", channelId],
    (client) =>
      client.getTasksPage({
        channel: channelId,
        limit: FETCH_LIMIT,
        ordering: "-last_activity_at",
        basic: true,
      }),
    {
      enabled: enabled && !!channelId,
      // The people in a space are not news; a visit is fresh enough.
      staleTime: 10 * 60_000,
      gcTime: 30 * 60_000,
      refetchOnWindowFocus: false,
      meta: AUTH_SCOPED_QUERY_META,
    },
  );

  const people = useMemo(() => {
    if (!data) return NO_PEOPLE;
    const seen = new Set<string>();
    const out: UserBasic[] = [];
    for (const task of data.tasks) {
      const author = task.created_by;
      if (!author || seen.has(author.uuid)) continue;
      if (out.length >= PARTICIPANTS_PER_SPACE) break;
      seen.add(author.uuid);
      out.push(author);
    }
    return out;
  }, [data]);

  return { people, isLoading };
}
