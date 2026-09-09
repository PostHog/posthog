import { useEffect, useState } from "react";
import zenHedgehog from "../../../assets/images/zen.png";
import {
  SessionStartupStatus,
  type SessionStartupStatusProps,
} from "./SessionStartupStatus";

type SessionInitializingViewProps = Omit<
  SessionStartupStatusProps,
  "showDetails"
>;

const REVEAL_DELAY_MS = 2000;

export function SessionInitializingView({
  executionTarget,
  phase,
}: SessionInitializingViewProps) {
  const [revealed, setRevealed] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setRevealed(true), REVEAL_DELAY_MS);
    return () => clearTimeout(timer);
  }, []);

  if (!revealed) {
    return (
      <div className="absolute inset-0 flex items-center justify-center gap-2 bg-background">
        <SessionStartupStatus
          executionTarget={executionTarget}
          phase={phase}
          showDetails={false}
        />
      </div>
    );
  }

  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center gap-5 bg-background">
      <div className="zen-float">
        <img src={zenHedgehog} alt="" className="block w-[160px]" />
      </div>
      <div className="flex flex-col items-center gap-2">
        <SessionStartupStatus executionTarget={executionTarget} phase={phase} />
      </div>
    </div>
  );
}
