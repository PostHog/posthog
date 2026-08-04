import { ArrowsClockwise, WifiHigh, WifiSlash } from "@phosphor-icons/react";
import { useService } from "@posthog/di/react";
import { useConnectivity } from "@posthog/ui/hooks/useConnectivity";
import { Box } from "@radix-ui/themes";
import { AnimatePresence, motion } from "framer-motion";
import { useEffect, useRef, useState } from "react";
import {
  CONNECTIVITY_CLIENT,
  type ConnectivityClient,
} from "./connectivityClient";

const BACK_ONLINE_VISIBLE_MS = 2_500;

/**
 * Shell banner for the global connectivity state: while offline, offers a Retry
 * that forces an immediate probe; briefly shows "Back online" on recovery.
 */
export function ConnectivityBanner() {
  const { isOnline } = useConnectivity();
  const client = useService<ConnectivityClient>(CONNECTIVITY_CLIENT);
  const [isChecking, setIsChecking] = useState(false);
  const [showBackOnline, setShowBackOnline] = useState(false);
  const wasOnlineRef = useRef(isOnline);

  useEffect(() => {
    const wasOnline = wasOnlineRef.current;
    wasOnlineRef.current = isOnline;

    if (!wasOnline && isOnline) {
      setIsChecking(false);
      setShowBackOnline(true);
      const timer = setTimeout(
        () => setShowBackOnline(false),
        BACK_ONLINE_VISIBLE_MS,
      );
      return () => clearTimeout(timer);
    }

    if (!isOnline) {
      setShowBackOnline(false);
    }

    return undefined;
  }, [isOnline]);

  const handleRetry = () => {
    if (isChecking) return;
    setIsChecking(true);
    void client
      .checkNow()
      .catch(() => undefined)
      .finally(() => setIsChecking(false));
  };

  const isVisible = !isOnline || showBackOnline;

  return (
    <AnimatePresence>
      {isVisible && (
        <motion.div
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: "auto", opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          transition={{ duration: 0.2, ease: "easeInOut" }}
          className="no-drag shrink-0 overflow-hidden"
        >
          <Box className="px-2 pt-2">
            {isOnline ? (
              <BackOnlineRow />
            ) : (
              <OfflineRow isChecking={isChecking} onRetry={handleRetry} />
            )}
          </Box>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

function OfflineRow({
  isChecking,
  onRetry,
}: {
  isChecking: boolean;
  onRetry: () => void;
}) {
  return (
    <div className="flex w-full items-center gap-2.5 rounded-md border border-(--amber-6) bg-(--amber-3) px-3 py-2 text-(--amber-11) text-[13px]">
      <WifiSlash size={16} weight="duotone" className="shrink-0" />
      <div className="flex min-w-0 flex-1 flex-col gap-0.5">
        <span className="font-medium">You're offline</span>
        <span className="text-(--amber-a11) text-[11px]">
          {isChecking
            ? "Checking connection…"
            : "Network actions are paused — reconnecting automatically."}
        </span>
      </div>
      <button
        type="button"
        disabled={isChecking}
        onClick={onRetry}
        className="flex shrink-0 items-center gap-1.5 rounded-2 bg-(--amber-a4) px-2 py-1 font-medium text-(--amber-11) text-[12px] transition-colors hover:bg-(--amber-a5) disabled:opacity-60"
      >
        <ArrowsClockwise
          size={13}
          className={isChecking ? "animate-spin" : undefined}
        />
        {isChecking ? "Checking…" : "Retry"}
      </button>
    </div>
  );
}

function BackOnlineRow() {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      transition={{ duration: 0.15 }}
      className="flex w-full items-center gap-2.5 rounded-md border border-(--green-a5) bg-(--green-a3) px-3 py-2 text-(--green-11) text-[13px]"
    >
      <WifiHigh size={16} weight="duotone" className="shrink-0" />
      <span className="font-medium">Back online</span>
    </motion.div>
  );
}
