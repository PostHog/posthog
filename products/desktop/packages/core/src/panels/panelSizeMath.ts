import { PANEL_SIZES } from "./panelConstants";
import type { GroupPanel } from "./panelTypes";

const MIN_PANEL_SIZE = 15;

export const normalizeSizes = (
  sizes: number[],
  childCount: number,
): number[] => {
  if (!sizes?.length) {
    return new Array(childCount).fill(100 / childCount);
  }

  const normalized = [...sizes];
  while (normalized.length < childCount) normalized.push(100 / childCount);
  if (normalized.length > childCount) normalized.length = childCount;

  const validSizes = normalized.map((size) =>
    size > 0 ? size : MIN_PANEL_SIZE,
  );
  const total = validSizes.reduce((sum, size) => sum + size, 0);

  if (total === 0) return new Array(childCount).fill(100 / childCount);

  const scaled = validSizes.map((size) => (size / total) * 100);
  const withMinimums = scaled.map((size) => Math.max(size, MIN_PANEL_SIZE));
  const finalTotal = withMinimums.reduce((sum, size) => sum + size, 0);

  return withMinimums.map((size) => (size / finalTotal) * 100);
};

export const calculateSplitSizes = (): [number, number] => [50, 50];

export const redistributeSizes = (
  sizes: number[],
  removedIndex: number,
): number[] => {
  if (sizes.length <= 1) return [100];

  const removedSize = sizes[removedIndex] ?? 0;
  const remainingSizes = sizes.filter((_, i) => i !== removedIndex);

  if (!remainingSizes.length) return [100];

  const remainingTotal = remainingSizes.reduce((sum, size) => sum + size, 0);

  if (remainingTotal === 0) {
    return new Array(remainingSizes.length).fill(100 / remainingSizes.length);
  }

  const redistributed = remainingSizes.map((size) => {
    const proportion = size / remainingTotal;
    return size + removedSize * proportion;
  });

  return normalizeSizes(redistributed, redistributed.length);
};

export function calculateDefaultSize(node: GroupPanel, index: number): number {
  return node.sizes?.[index] ?? 100 / node.children.length;
}

export function shouldUpdateSizes(
  currentSizes: number[],
  storeSizes: number[],
): boolean {
  if (currentSizes.length !== storeSizes.length) {
    return false;
  }

  return currentSizes.some(
    (size, i) =>
      Math.abs(size - storeSizes[i]) > PANEL_SIZES.SIZE_DIFF_THRESHOLD,
  );
}
