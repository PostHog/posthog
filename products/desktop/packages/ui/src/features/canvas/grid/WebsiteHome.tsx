import { useHostTRPC } from "@posthog/host-router/react";
import { Button, Heading, Spinner } from "@posthog/quill";
import { useCanvasChatPanelStore } from "@posthog/ui/features/canvas/stores/canvasChatPanelStore";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { GridCanvasView } from "./GridCanvasView";

/**
 * The user's home tab: a personal grid canvas, provisioned on first open
 * (idempotent get-or-create) and composed like any other grid canvas — draw a
 * box and describe it.
 */
export function WebsiteHome() {
  const trpc = useHostTRPC();
  const [editing, setEditing] = useState(false);
  // Entering edit opens the canvas chat dock, like the freeform Edit button.
  const openChat = useCanvasChatPanelStore((state) => state.openChat);
  const { data: home } = useQuery(
    // Provisioning is an idempotent get-or-create, so query semantics are
    // safe and give caching + dedupe across remounts for free.
    trpc.dashboards.home.queryOptions(undefined, { staleTime: Infinity }),
  );

  if (!home) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner />
      </div>
    );
  }
  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-center justify-between border-(--gray-4) border-b px-4 py-2">
        <Heading size="lg">Home</Heading>
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
