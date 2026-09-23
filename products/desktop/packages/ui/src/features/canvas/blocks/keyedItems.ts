export interface KeyedItem<T> {
  key: string;
  item: T;
  index: number;
}

export function keyedItems<T>(
  items: T[],
  keyOf: (item: T) => string,
): KeyedItem<T>[] {
  const seen = new Map<string, number>();
  return items.map((item, index) => {
    const base = keyOf(item);
    const count = seen.get(base) ?? 0;
    seen.set(base, count + 1);
    return { key: count === 0 ? base : `${base}#${count}`, item, index };
  });
}
