import {
  MagnifyingGlassMinus,
  MagnifyingGlassPlus,
  Trash,
} from "@phosphor-icons/react";
import { getCellCount } from "@posthog/core/command-center/grid";
import { Flex, Select, Text } from "@radix-ui/themes";
import { useCallback } from "react";
import {
  type LayoutPreset,
  useCommandCenterStore,
} from "../commandCenterStore";
import type { StatusSummary } from "../hooks/useCommandCenterData";
import { destroyTerminalCells } from "../terminalCells";

function LayoutIcon({ cols, rows }: { cols: number; rows: number }) {
  const size = 14;
  const gap = 1.5;
  const cellW = (size - gap * (cols - 1)) / cols;
  const cellH = (size - gap * (rows - 1)) / rows;

  const rects: React.ReactElement[] = [];
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      rects.push(
        <rect
          key={`${r}-${c}`}
          x={c * (cellW + gap)}
          y={r * (cellH + gap)}
          width={cellW}
          height={cellH}
          rx={1}
          fill="currentColor"
          opacity={0.5}
        />,
      );
    }
  }

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      role="img"
      aria-label={`${cols} by ${rows} grid`}
    >
      {rects}
    </svg>
  );
}

const LAYOUT_OPTIONS: {
  value: LayoutPreset;
  label: string;
  cols: number;
  rows: number;
}[] = [
  { value: "1x1", label: "1x1", cols: 1, rows: 1 },
  { value: "2x1", label: "2x1", cols: 2, rows: 1 },
  { value: "1x2", label: "1x2", cols: 1, rows: 2 },
  { value: "2x2", label: "2x2", cols: 2, rows: 2 },
  { value: "3x2", label: "3x2", cols: 3, rows: 2 },
  { value: "3x3", label: "3x3", cols: 3, rows: 3 },
];

interface CommandCenterToolbarProps {
  summary: StatusSummary;
}

function StatusSummaryText({ summary }: { summary: StatusSummary }) {
  if (summary.total === 0) return null;

  const parts: string[] = [
    `${summary.total} agent${summary.total !== 1 ? "s" : ""}`,
  ];
  if (summary.running > 0) parts.push(`${summary.running} running`);
  if (summary.waiting > 0) parts.push(`${summary.waiting} waiting`);

  return (
    <Text className="text-[12px] text-gray-10">{parts.join(" \u00b7 ")}</Text>
  );
}

export function CommandCenterToolbar({ summary }: CommandCenterToolbarProps) {
  const layout = useCommandCenterStore((s) => s.layout);
  const setLayout = useCommandCenterStore((s) => s.setLayout);
  const clearAll = useCommandCenterStore((s) => s.clearAll);

  const handleSetLayout = useCallback(
    (preset: LayoutPreset) => {
      const cells = useCommandCenterStore.getState().cells;
      destroyTerminalCells(cells.slice(getCellCount(preset)));
      setLayout(preset);
    },
    [setLayout],
  );

  const handleClearAll = useCallback(() => {
    destroyTerminalCells(useCommandCenterStore.getState().cells);
    clearAll();
  }, [clearAll]);

  const zoom = useCommandCenterStore((s) => s.zoom);
  const zoomIn = useCommandCenterStore((s) => s.zoomIn);
  const zoomOut = useCommandCenterStore((s) => s.zoomOut);

  return (
    <Flex
      align="center"
      gap="3"
      px="3"
      py="2"
      className="no-drag shrink-0 border-gray-6 border-b"
    >
      <Select.Root
        value={layout}
        onValueChange={(v) => handleSetLayout(v as LayoutPreset)}
      >
        <Select.Trigger variant="ghost" className="text-[12px]" />
        <Select.Content position="popper">
          {LAYOUT_OPTIONS.map((opt) => (
            <Select.Item key={opt.value} value={opt.value}>
              <Flex align="center" gap="2">
                <LayoutIcon cols={opt.cols} rows={opt.rows} />
                {opt.label}
              </Flex>
            </Select.Item>
          ))}
        </Select.Content>
      </Select.Root>

      <StatusSummaryText summary={summary} />

      <Flex align="center" gap="1">
        <button
          type="button"
          onClick={zoomOut}
          disabled={zoom <= 0.5}
          className="flex h-5 w-5 items-center justify-center rounded text-gray-10 transition-colors hover:bg-gray-4 hover:text-gray-12 disabled:opacity-40"
          title="Zoom out"
        >
          <MagnifyingGlassMinus size={14} />
        </button>
        <Text className="w-8 text-center text-[12px] text-gray-10">
          {Math.round(zoom * 100)}%
        </Text>
        <button
          type="button"
          onClick={zoomIn}
          disabled={zoom >= 1.5}
          className="flex h-5 w-5 items-center justify-center rounded text-gray-10 transition-colors hover:bg-gray-4 hover:text-gray-12 disabled:opacity-40"
          title="Zoom in"
        >
          <MagnifyingGlassPlus size={14} />
        </button>
      </Flex>

      <div className="flex-1" />

      <button
        type="button"
        onClick={handleClearAll}
        className="flex items-center gap-1 rounded px-1.5 py-0.5 text-[12px] text-gray-10 transition-colors hover:bg-gray-4 hover:text-gray-12"
        title="Clear all cells"
      >
        <Trash size={12} />
        Clear
      </button>
    </Flex>
  );
}
