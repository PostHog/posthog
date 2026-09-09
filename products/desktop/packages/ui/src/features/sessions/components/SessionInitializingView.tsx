import { Spinner } from "@posthog/ui/primitives/Spinner";
import { useEffect, useState } from "react";
import zenHedgehog from "../../../assets/images/zen.png";

interface SessionInitializingViewProps {
  executionTarget: "cloud" | "local";
}

const REVEAL_DELAY_MS = 2000;

export function SessionInitializingView({
  executionTarget,
}: SessionInitializingViewProps) {
  const subtitle =
    executionTarget === "local"
      ? "Connecting to Pi on this device."
      : "Connecting to your cloud runner.";
  const [revealed, setRevealed] = useState(false);

  useEffect(() => {
    const timer = setTimeout(() => setRevealed(true), REVEAL_DELAY_MS);
    return () => clearTimeout(timer);
  }, []);

  if (!revealed) {
    return (
      <div className="absolute inset-0 flex items-center justify-center gap-2 bg-background">
        <Spinner size="md" className="text-gray-9" />
        <span className="font-medium text-base">Loading</span>
      </div>
    );
  }

  return (
    <div className="absolute inset-0 flex flex-col items-center justify-center gap-5 bg-background">
      <div className="zen-float">
        <img src={zenHedgehog} alt="" className="block w-[160px]" />
      </div>
      <div className="flex flex-col items-center gap-2">
        <div className="flex items-center gap-2">
          <Spinner size="md" className="text-gray-9" />
          <span className="font-medium text-base">Loading</span>
        </div>
        <span className="text-gray-11 text-sm">{subtitle}</span>
      </div>
    </div>
  );
}
