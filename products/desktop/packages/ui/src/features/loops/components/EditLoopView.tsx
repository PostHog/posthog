import { useLoop } from "../hooks/useLoop";
import { LoopLoadError } from "./LoopFallbacks";
import { LoopForm } from "./LoopForm";

export function EditLoopView({ loopId }: { loopId: string }) {
  const { data: loop, isLoading, isError } = useLoop(loopId);

  if (isLoading) {
    return (
      <div className="mx-auto max-w-2xl px-6 py-6">
        <div className="h-24 animate-pulse rounded-(--radius-2) border border-border bg-(--gray-2)" />
      </div>
    );
  }

  if (isError || !loop) {
    return <LoopLoadError />;
  }

  return <LoopForm loop={loop} />;
}
