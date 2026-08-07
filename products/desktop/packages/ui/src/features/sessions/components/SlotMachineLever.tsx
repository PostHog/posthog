import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { fireFrom } from "@posthog/ui/primitives/confetti";
import { motion } from "framer-motion";
import { useCallback, useEffect, useRef, useState } from "react";

/** Reel faces. The hedgehog is the jackpot symbol. */
const REEL_SYMBOLS = ["🍒", "🍋", "🔔", "⭐", "💎", "7️⃣", "🦔"] as const;

/** How often spinning reels swap faces, in ms. */
const SPIN_INTERVAL_MS = 80;

/**
 * When a run ends, the reels don't stop dead — they decelerate and lock one at
 * a time, left to right, at these offsets (ms) so you can watch the result land.
 */
const LAND_STAGGER_MS = [320, 640, 980] as const;

/** Odds the landed result is a forced triple-hedgehog jackpot. The house is generous. */
const JACKPOT_RATE = 0.2;

const JACKPOT_RESULT: [string, string, string] = ["🦔", "🦔", "🦔"];

function randomSymbol(): string {
  return REEL_SYMBOLS[Math.floor(Math.random() * REEL_SYMBOLS.length)];
}

function randomReels(): [string, string, string] {
  return [randomSymbol(), randomSymbol(), randomSymbol()];
}

/** Decide where the reels land once a run finishes. */
function rollResult(): [string, string, string] {
  if (Math.random() < JACKPOT_RATE) return [...JACKPOT_RESULT];
  return randomReels();
}

interface SlotMachineLeverProps {
  /** Whether the agent is actively generating — the reels spin while it is. */
  spinning: boolean;
}

/**
 * Easter egg gated behind the `slotMachineMode` setting: a tiny slot machine in
 * the session footer. The reels spin while a task runs, then decelerate and
 * lock one reel at a time when it finishes so you can see what you got. Three
 * hedgehogs is the jackpot — and pays out in confetti.
 */
export function SlotMachineLever({ spinning }: SlotMachineLeverProps) {
  const enabled = useSettingsStore((state) => state.slotMachineMode);
  const [reels, setReels] = useState<[string, string, string]>(randomReels);
  // Which reels are still spinning. They lock left-to-right as a run lands.
  const [active, setActive] = useState<[boolean, boolean, boolean]>([
    false,
    false,
    false,
  ]);
  const [jackpot, setJackpot] = useState(false);
  const reelBoxRef = useRef<HTMLDivElement>(null);
  const landTimers = useRef<ReturnType<typeof setTimeout>[]>([]);
  // Tracks whether the reels were spinning, so we only run the landing sequence
  // after a real run (not on mount, when `spinning` starts out false).
  const wasSpinning = useRef(false);

  const clearLandTimers = useCallback(() => {
    for (const timer of landTimers.current) {
      clearTimeout(timer);
    }
    landTimers.current = [];
  }, []);

  // Clear pending land timers on unmount so they don't fire against stale state.
  useEffect(() => clearLandTimers, [clearLandTimers]);

  // Start spinning when a run begins; decelerate and land when it ends.
  useEffect(() => {
    if (!enabled) return;
    if (spinning) {
      clearLandTimers();
      setJackpot(false);
      wasSpinning.current = true;
      setActive([true, true, true]);
      return;
    }
    if (!wasSpinning.current) return;
    wasSpinning.current = false;

    const result = rollResult();
    LAND_STAGGER_MS.forEach((delay, index) => {
      const timer = setTimeout(() => {
        setReels((prev) => {
          const next: [string, string, string] = [...prev];
          next[index] = result[index];
          return next;
        });
        setActive((prev) => {
          const next: [boolean, boolean, boolean] = [...prev];
          next[index] = false;
          return next;
        });
        // Last reel just locked — pay out if it's three hedgehogs.
        if (index === LAND_STAGGER_MS.length - 1) {
          const won = result.every((symbol) => symbol === "🦔");
          if (won) {
            setJackpot(true);
            if (reelBoxRef.current) {
              fireFrom(reelBoxRef.current, {
                particleCount: 60,
                spread: 80,
                startVelocity: 28,
              });
            }
          }
        }
      }, delay);
      landTimers.current.push(timer);
    });
  }, [spinning, enabled, clearLandTimers]);

  // Randomise only the reels that are still spinning.
  useEffect(() => {
    if (!active.some(Boolean)) return;
    const id = setInterval(() => {
      setReels(
        (prev) =>
          prev.map((symbol, i) => (active[i] ? randomSymbol() : symbol)) as [
            string,
            string,
            string,
          ],
      );
    }, SPIN_INTERVAL_MS);
    return () => clearInterval(id);
  }, [active]);

  if (!enabled) return null;

  return (
    <motion.div
      ref={reelBoxRef}
      animate={
        jackpot ? { scale: [1, 1.25, 1], rotate: [0, -4, 4, 0] } : { scale: 1 }
      }
      transition={jackpot ? { duration: 0.6, ease: "easeInOut" } : undefined}
      className={`flex shrink-0 select-none items-center gap-1 rounded-sm border px-1 py-[1px] ${
        jackpot
          ? "border-yellow-7 bg-yellow-3 shadow-[0_0_8px_rgba(245,190,42,0.7)]"
          : "border-gray-6 bg-gray-2"
      }`}
      style={{ WebkitUserSelect: "none" }}
    >
      {reels.map((symbol, index) => (
        <motion.span
          // biome-ignore lint/suspicious/noArrayIndexKey: fixed 3-reel layout
          key={index}
          animate={active[index] ? { y: [-1, 1, -1] } : { y: 0 }}
          transition={
            active[index]
              ? { duration: 0.16, repeat: Infinity, ease: "linear" }
              : { type: "spring", stiffness: 500, damping: 18 }
          }
          className="w-[14px] text-center text-[12px] leading-none"
        >
          {symbol}
        </motion.span>
      ))}
    </motion.div>
  );
}
