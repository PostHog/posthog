import { WarningIcon } from "@phosphor-icons/react";
import { useHostTRPC } from "@posthog/host-router/react";
import {
  Button,
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
  Heading,
  Spinner,
} from "@posthog/quill";
import { AUTH_SCOPED_QUERY_META } from "@posthog/ui/features/auth/useCurrentUser";
import { useCanvasChatPanelStore } from "@posthog/ui/features/canvas/stores/canvasChatPanelStore";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { GridCanvasView } from "./GridCanvasView";

/**
 * The user's home tab: a personal grid canvas, provisioned on first open
 * (idempotent get-or-create) and composed like any other grid canvas — draw a
 * box and describe it.
 */
export function HomeView() {
  const trpc = useHostTRPC();
  const [editing, setEditing] = useState(false);
  // Entering edit opens the canvas chat dock, like the freeform Edit button.
  const openChat = useCanvasChatPanelStore((state) => state.openChat);
  const {
    data: home,
    isError,
    isFetching,
    refetch,
  } = useQuery(
    // Provisioning is an idempotent get-or-create, so query semantics are
    // safe and give caching + dedupe across remounts for free.
    //
    // The auth-scoped meta is load-bearing rather than tidy here: this query
    // takes no input, so every account on the machine shares one cache key,
    // and `staleTime: Infinity` (which keeps a mounted Home from re-running
    // provisioning) means nothing else would ever refresh it. Without the meta
    // a logout, org switch, or project switch leaves the previous user's
    // personal home canvas id in the cache for the next one.
    trpc.dashboards.home.queryOptions(undefined, {
      meta: AUTH_SCOPED_QUERY_META,
      staleTime: Infinity,
    }),
  );

  // Provisioning is a live round trip (it get-or-creates the canvas) and can
  // fail — offline, or a backend error. Without this the failed query looks
  // identical to a slow one and Home dead-ends on the spinner below.
  if (isError && !home) {
    return (
      <Empty className="h-full border-0">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <WarningIcon size={24} />
          </EmptyMedia>
          <EmptyTitle>Couldn't load Home</EmptyTitle>
          <EmptyDescription>
            Setting up your home canvas failed. Check your connection and try
            again.
          </EmptyDescription>
        </EmptyHeader>
        <EmptyContent>
          <Button
            variant="primary"
            size="default"
            loading={isFetching}
            disabled={isFetching}
            onClick={() => void refetch()}
          >
            Try again
          </Button>
        </EmptyContent>
      </Empty>
    );
  }

  if (!home) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner />
      </div>
    );
  }
  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-center justify-between border-border border-b px-4 py-2">
        <Heading size="lg" className="font-bold">
          Home
        </Heading>
        <Button
          variant={editing ? "primary" : "outline"}
          size="sm"
          onClick={() => {
            if (!editing) openChat();
            setEditing(!editing);
          }}
        >
          {editing ? "Done" : "Edit"}
        </Button>
      </div>
      <div className="relative min-h-0 flex-1">
        <GridCanvasView canvasId={home.id} interactive={editing} />
      </div>
    </div>
  );
}
