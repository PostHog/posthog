import { useEffect, useRef, useState } from "react";
import { AppState, type AppStateStatus } from "react-native";

/**
 * Hook that triggers a re-render at the specified interval.
 * Pauses when the app goes to background.
 * Pass 0 to disable the interval.
 */
export function usePeriodicRerender(milliseconds: number): void {
  const [, setTick] = useState(0);
  const intervalIdRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    // Don't start interval if milliseconds is 0 or negative
    if (milliseconds <= 0) {
      return;
    }

    const startInterval = (): void => {
      if (intervalIdRef.current) {
        return;
      }
      intervalIdRef.current = setInterval(
        () => setTick((state) => state + 1),
        milliseconds,
      );
    };

    const stopInterval = (): void => {
      if (intervalIdRef.current) {
        clearInterval(intervalIdRef.current);
        intervalIdRef.current = null;
      }
    };

    const handleAppStateChange = (nextAppState: AppStateStatus): void => {
      if (nextAppState === "active") {
        setTick((state) => state + 1); // Immediate update when returning to foreground
        startInterval();
      } else {
        stopInterval();
      }
    };

    // Start immediately
    startInterval();

    const subscription = AppState.addEventListener(
      "change",
      handleAppStateChange,
    );

    return () => {
      stopInterval();
      subscription.remove();
    };
  }, [milliseconds]);
}
