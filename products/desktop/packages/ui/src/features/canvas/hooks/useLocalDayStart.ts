import { useEffect, useState } from "react";

function startOfLocalDay(): number {
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  return start.getTime();
}

/**
 * Today, as a timestamp that changes when the day does.
 *
 * A list headed "Today" and "Yesterday" is wrong the moment local midnight
 * passes, and a sidebar left open on a quiet space has nothing else to make it
 * re-render — its items can be identical for hours. Anything that dates rows
 * relative to now reads this instead of calling `new Date()` mid-render.
 */
export function useLocalDayStart(): number {
  const [dayStart, setDayStart] = useState(startOfLocalDay);

  useEffect(() => {
    // setDate rather than adding 24 hours: a DST change makes a local day 23 or
    // 25 hours long, and the timer has to land after midnight either way.
    const nextMidnight = new Date(dayStart);
    nextMidnight.setDate(nextMidnight.getDate() + 1);
    const timer = setTimeout(
      () => setDayStart(startOfLocalDay()),
      Math.max(nextMidnight.getTime() - Date.now(), 0) + 1_000,
    );
    return () => clearTimeout(timer);
  }, [dayStart]);

  return dayStart;
}
