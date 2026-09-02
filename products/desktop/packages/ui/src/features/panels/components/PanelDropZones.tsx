import { useDroppable } from "@dnd-kit/react";
import { Box } from "@radix-ui/themes";
import type React from "react";
import type { SplitDirection } from "../panelTypes";

type DropZoneType = SplitDirection | "center";

interface PanelDropZonesProps {
  panelId: string;
  isDragging: boolean;
  allowSplit?: boolean; // Whether to show edge drop zones for splitting
}

interface DropZoneProps {
  panelId: string;
  zone: DropZoneType;
  style: React.CSSProperties;
}

const DropZone: React.FC<DropZoneProps> = ({ panelId, zone, style }) => {
  const { ref, isDropTarget } = useDroppable({
    id: `drop-${panelId}-${zone}`,
    data: { panelId, zone, type: "panel" },
  });

  return (
    <Box
      ref={ref}
      className={`drop-zone drop-zone-${zone} pointer-events-auto absolute z-[100] transition-all duration-150`}
      style={{
        ...style,
        backgroundColor: isDropTarget ? "var(--gray-8)" : "transparent",
        opacity: isDropTarget ? 0.3 : 0,
      }}
    />
  );
};

const ZONE_SIZE = "20%";

const ZONE_CONFIGS: Array<{ zone: DropZoneType; style: React.CSSProperties }> =
  [
    {
      zone: "top",
      style: { top: 0, left: 0, right: 0, height: ZONE_SIZE },
    },
    {
      zone: "bottom",
      style: { bottom: 0, left: 0, right: 0, height: ZONE_SIZE },
    },
    {
      zone: "left",
      style: { top: 0, left: 0, bottom: 0, width: ZONE_SIZE },
    },
    {
      zone: "right",
      style: { top: 0, right: 0, bottom: 0, width: ZONE_SIZE },
    },
    {
      zone: "center",
      style: {
        top: ZONE_SIZE,
        left: ZONE_SIZE,
        right: ZONE_SIZE,
        bottom: ZONE_SIZE,
      },
    },
  ];

export const PanelDropZones: React.FC<PanelDropZonesProps> = ({
  panelId,
  isDragging,
  allowSplit = true,
}) => {
  if (!isDragging) return null;

  // Filter zones based on allowSplit
  const visibleZones = allowSplit
    ? ZONE_CONFIGS
    : ZONE_CONFIGS.filter((config) => config.zone === "center");

  return (
    <Box
      style={{
        zIndex: 100,
      }}
      className="pointer-events-none absolute inset-0"
    >
      {visibleZones.map(({ zone, style }) => (
        <DropZone key={zone} panelId={panelId} zone={zone} style={style} />
      ))}
    </Box>
  );
};
