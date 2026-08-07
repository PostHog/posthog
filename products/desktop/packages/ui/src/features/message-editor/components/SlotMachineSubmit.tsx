import { Tooltip } from "@radix-ui/themes";
import { motion, useAnimationControls } from "framer-motion";
import { useCallback, useEffect, useRef } from "react";

// The arm reaches the bottom of its swing at ~270ms (0.45 of the 0.6s tween).
// Fire the prompt there so the pull visibly completes before submitting flips
// the composer into loading and unmounts the lever.
const SUBMIT_DELAY_MS = 260;

interface SlotMachineSubmitProps {
  /** Blocks the pull and greys out the handle (empty editor / external block). */
  disabled: boolean;
  /** Fires the prompt. Called on the lever's downswing. */
  onSubmit: () => void;
  /**
   * Tour anchor prefix. When set, the lever carries `data-tour="<target>-submit"`
   * so the create-first-task tour's submit step can still find and advance off
   * it while slot machine mode is enabled.
   */
  tourTarget?: string;
}

/**
 * A real slot-machine arm mounted to the right of the composer. Stands in for
 * the send button while the `slotMachineMode` easter egg is enabled — pull the
 * lever to fire your prompt. Every run is a gamble. 🎰
 */
export function SlotMachineSubmit({
  disabled,
  onSubmit,
  tourTarget,
}: SlotMachineSubmitProps) {
  const lever = useAnimationControls();
  const submitTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Don't leave a pending submit timer to fire after the lever unmounts.
  useEffect(() => {
    return () => {
      if (submitTimeout.current !== null) {
        clearTimeout(submitTimeout.current);
      }
    };
  }, []);

  const handleClick = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation();
      if (disabled) return;
      // Swing the arm down and let it spring back. The submit is deferred to
      // the bottom of the swing so the pull plays out before the prompt fires.
      void lever.start({
        rotate: [0, 72, 0],
        transition: {
          duration: 0.6,
          times: [0, 0.45, 1],
          ease: ["easeIn", "easeOut"],
        },
      });
      if (submitTimeout.current !== null) {
        clearTimeout(submitTimeout.current);
      }
      submitTimeout.current = setTimeout(onSubmit, SUBMIT_DELAY_MS);
    },
    [disabled, lever, onSubmit],
  );

  return (
    <Tooltip
      content={disabled ? "Enter a message" : "Pull to gamble on your task 🎰"}
    >
      <button
        type="button"
        onClick={handleClick}
        disabled={disabled}
        aria-label="Pull the slot machine lever to send"
        className="group relative flex w-9 shrink-0 cursor-pointer items-end justify-center self-stretch disabled:cursor-not-allowed disabled:opacity-40"
        {...(tourTarget && { "data-tour": `${tourTarget}-submit` })}
      >
        {/* Housing the arm pivots out of, bolted to the side of the machine. */}
        <span className="-translate-x-1/2 absolute bottom-0 left-1/2 h-3 w-5 rounded-t-[3px] bg-gradient-to-b from-gray-7 to-gray-9 shadow-sm" />
        <span className="-translate-x-1/2 absolute bottom-[5px] left-1/2 h-[3px] w-[3px] rounded-full bg-gray-11" />

        {/* The arm: a chrome shaft topped with the red ball, pivoting at base. */}
        <motion.span
          animate={lever}
          style={{ originX: 0.5, originY: 1 }}
          className="relative z-10 mb-[7px] flex flex-col items-center"
        >
          <span className="h-[14px] w-[14px] rounded-full bg-gradient-to-br from-red-8 to-red-10 shadow-[0_1px_2px_rgba(0,0,0,0.35),inset_0_1px_1px_rgba(255,255,255,0.5)] group-hover:from-red-7 group-hover:to-red-9" />
          <span className="h-[26px] w-[4px] rounded-full bg-gradient-to-r from-gray-8 via-gray-6 to-gray-9" />
        </motion.span>
      </button>
    </Tooltip>
  );
}
