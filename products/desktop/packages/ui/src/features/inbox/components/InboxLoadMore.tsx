import { Button } from "@posthog/ui/primitives/Button";
import { Flex } from "@radix-ui/themes";

/**
 * "Load more" control for the paginated inbox tabs. The report lists are backed
 * by an infinite query (page size 100) but nothing advanced it, so tabs capped
 * at the first page. This renders the next-page trigger below the list.
 *
 * `hasNextPage` from React Query is `boolean | undefined`; render nothing until
 * there's a confirmed next page.
 */
export function InboxLoadMore({
  hasNextPage,
  isFetchingNextPage,
  onLoadMore,
}: {
  hasNextPage: boolean | undefined;
  isFetchingNextPage: boolean;
  onLoadMore: () => void;
}) {
  if (!hasNextPage) return null;

  return (
    <Flex justify="center" className="py-2">
      <Button
        type="button"
        variant="soft"
        color="gray"
        loading={isFetchingNextPage}
        disabled={isFetchingNextPage}
        onClick={onLoadMore}
      >
        Load more
      </Button>
    </Flex>
  );
}
