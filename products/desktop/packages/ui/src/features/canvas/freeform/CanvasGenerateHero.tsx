import { ShapesIcon } from "@phosphor-icons/react";
import { CanvasBlocksStarter } from "@posthog/ui/features/canvas/blocks/CanvasBlocks";
import { CANVAS_GENERATE_SUGGESTIONS } from "@posthog/ui/features/canvas/freeform/canvasGenerateSuggestions";
import { FreeformGenerateBar } from "@posthog/ui/features/canvas/freeform/FreeformGenerateBar";
import type { EditorHandle } from "@posthog/ui/features/message-editor/types";
import { SuggestedPromptCard } from "@posthog/ui/features/task-detail/components/SuggestedPromptCard";
import { DotPatternBackground } from "@posthog/ui/primitives/DotPatternBackground";
import { useRef } from "react";

// The empty-canvas landing state: a centered composer with starter-prompt
// suggestions below it. Once the user submits, the canvas record records a
// generation task and FreeformCanvasView swaps this hero for the canvas +
// side-panel layout — the composer "floats to the side".
export function CanvasGenerateHero({
  dashboardId,
  channelId,
  channelName,
  name,
  templateId,
  onStarted,
}: {
  dashboardId: string;
  channelId: string;
  channelName: string;
  name: string;
  templateId?: string;
  onStarted?: (taskId: string) => void;
}) {
  // Lets a suggestion card drop its prompt straight into the editor.
  const editorRef = useRef<EditorHandle>(null);

  return (
    <div className="relative flex h-full w-full flex-col items-center justify-center overflow-y-auto px-4 py-10">
      <DotPatternBackground className="h-full" />
      <div className="z-[1] flex w-full max-w-[620px] flex-col gap-5">
        <div className="flex flex-col items-center gap-2 text-center">
          <div className="flex size-10 items-center justify-center rounded-xl bg-accent-3 text-accent-9">
            <ShapesIcon size={20} weight="duotone" />
          </div>
          <h2 className="font-bold text-foreground text-xl">Build a canvas</h2>
          <p className="text-muted-foreground text-sm">
            Describe it and an agent builds it, or drop in blocks yourself.
          </p>
        </div>

        <FreeformGenerateBar
          ref={editorRef}
          sessionId={`canvas:${dashboardId}`}
          dashboardId={dashboardId}
          channelId={channelId}
          channelName={channelName}
          name={name}
          templateId={templateId}
          onStarted={onStarted}
        />

        <div className="flex flex-col gap-2">
          <span className="px-1 font-medium text-muted-foreground text-xs">
            Suggestions
          </span>
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {CANVAS_GENERATE_SUGGESTIONS.map((suggestion) => (
              <SuggestedPromptCard
                key={suggestion.label}
                suggestion={suggestion}
                onSelect={() => {
                  editorRef.current?.setContent(suggestion.prompt);
                  editorRef.current?.focus();
                }}
              />
            ))}
          </div>
        </div>

        <div className="flex flex-col gap-2">
          <span className="px-1 font-medium text-muted-foreground text-xs">
            Build it yourself
          </span>
          <CanvasBlocksStarter canvasId={dashboardId} />
        </div>
      </div>
    </div>
  );
}
