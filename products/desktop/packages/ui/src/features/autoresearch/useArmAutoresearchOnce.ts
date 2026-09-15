import { useEffect, useRef } from "react";

interface ArmAutoresearchOnceOptions {
  /** The composer was opened asking for autoresearch. */
  requested: boolean;
  /** Arming can take effect now. */
  ready: boolean;
  /** Autoresearch is already on for this composer. */
  armed: boolean;
  arm: () => void;
}

/**
 * Arms autoresearch once for a composer that was opened asking for it.
 * Turning it off afterwards does not bring it back.
 */
export function useArmAutoresearchOnce({
  requested,
  ready,
  armed,
  arm,
}: ArmAutoresearchOnceOptions): void {
  const handledRef = useRef(false);

  useEffect(() => {
    if (!requested || !ready || handledRef.current) return;
    handledRef.current = true;
    if (!armed) arm();
  }, [requested, ready, armed, arm]);
}
