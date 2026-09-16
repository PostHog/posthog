import { SquaresFourIcon } from "@phosphor-icons/react";
import { Button } from "@posthog/quill";
import { ChromeBar } from "@posthog/ui/primitives/ChromeBar";
import type { ReactElement } from "react";
import { useClassicViewStore } from "./classicViewStore";

export function ClassicSidebar(): ReactElement {
  const openDashboards = useClassicViewStore((state) => state.openDashboards);
  return (
    <nav
      aria-label="Classic navigation"
      className="flex min-h-0 flex-1 flex-col"
    >
      <ChromeBar>
        <span className="font-medium text-xs">Classic</span>
      </ChromeBar>
      <div className="p-2">
        <Button
          onClick={openDashboards}
          className="w-full justify-start bg-fill-selected"
          data-selected
        >
          <SquaresFourIcon />
          Dashboards
        </Button>
      </div>
      <p className="mt-auto p-3 text-muted-foreground text-xs">
        The PostHog web app in desktop. This preview supports dashboards. Chat
        stays in desktop.
      </p>
    </nav>
  );
}
