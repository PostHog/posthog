import { ShapesIcon } from "@phosphor-icons/react";
import { CANVAS_GENERATE_SUGGESTIONS } from "@posthog/ui/features/canvas/freeform/canvasGenerateSuggestions";
import { FreeformGenerateBar } from "@posthog/ui/features/canvas/freeform/FreeformGenerateBar";
import type { EditorHandle } from "@posthog/ui/features/message-editor/types";
import { SuggestedPromptCard } from "@posthog/ui/features/task-detail/components/SuggestedPromptCard";
import { DotPatternBackground } from "@posthog/ui/primitives/DotPatternBackground";
import { Flex, Text } from "@radix-ui/themes";
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
    <Flex
      direction="column"
      align="center"
      justify="center"
      className="relative h-full w-full overflow-y-auto px-4 py-10"
    >
      <DotPatternBackground className="h-full" />
      <Flex direction="column" gap="5" className="z-[1] w-full max-w-[620px]">
        <Flex direction="column" align="center" gap="2" className="text-center">
          <Flex
            align="center"
            justify="center"
            className="size-10 rounded-xl bg-accent-3 text-accent-9"
          >
            <ShapesIcon size={20} weight="duotone" />
          </Flex>
          <Text size="5" weight="bold" className="text-gray-12">
            Build a canvas
          </Text>
          <Text size="2" className="text-gray-10">
            Describe what you want and an agent builds it.
          </Text>
        </Flex>

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

        <Flex direction="column" gap="2">
          <Text size="1" weight="medium" className="px-1 text-gray-11">
            Suggestions
          </Text>
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
        </Flex>
      </Flex>
    </Flex>
  );
}
