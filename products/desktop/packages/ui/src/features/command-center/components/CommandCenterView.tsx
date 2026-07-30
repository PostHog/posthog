import { Box, Flex } from "@radix-ui/themes";
import { useEffect } from "react";
import { useSetHeaderContent } from "../../../hooks/useSetHeaderContent";
import { useTaskViewed } from "../../sidebar/useTaskViewed";
import { useCommandCenterStore } from "../commandCenterStore";
import { useAutofillCommandCenter } from "../hooks/useAutofillCommandCenter";
import { useCommandCenterData } from "../hooks/useCommandCenterData";
import { CommandCenterGrid } from "./CommandCenterGrid";
import { CommandCenterToolbar } from "./CommandCenterToolbar";

export function CommandCenterView() {
  const layout = useCommandCenterStore((s) => s.layout);
  const { cells, summary } = useCommandCenterData();
  const { markAsViewed } = useTaskViewed();

  useAutofillCommandCenter();

  const visibleTaskIdsKey = cells
    .map((c) => c.taskId)
    .filter(Boolean)
    .join(",");

  useEffect(() => {
    if (!visibleTaskIdsKey) return;
    for (const taskId of visibleTaskIdsKey.split(",")) {
      markAsViewed(taskId);
    }
  }, [visibleTaskIdsKey, markAsViewed]);

  // Root-level page: no breadcrumb row. Its own toolbar names the view, and
  // there's no parent space to walk back to, so the bar was an empty frame.
  // (Pushing null also collapses the row inside the Channels space, where
  // WebsiteLayout renders whatever the active view puts in the header store.)
  useSetHeaderContent(null);

  return (
    <Flex direction="column" height="100%">
      <CommandCenterToolbar summary={summary} />
      <Box className="min-h-0 flex-1">
        <CommandCenterGrid layout={layout} cells={cells} />
      </Box>
    </Flex>
  );
}
