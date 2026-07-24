import { Lightning } from "@phosphor-icons/react";
import { Box, Flex, Text } from "@radix-ui/themes";
import { useEffect, useMemo } from "react";
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

  const headerContent = useMemo(
    () => (
      <Flex align="center" gap="2" className="w-full min-w-0">
        <Lightning size={12} className="shrink-0 text-gray-10" />
        <Text
          className="truncate whitespace-nowrap font-medium text-[13px]"
          title="Command Center"
        >
          Command Center
        </Text>
      </Flex>
    ),
    [],
  );

  useSetHeaderContent(headerContent);

  return (
    <Flex direction="column" height="100%">
      <CommandCenterToolbar summary={summary} />
      <Box className="min-h-0 flex-1">
        <CommandCenterGrid layout={layout} cells={cells} />
      </Box>
    </Flex>
  );
}
