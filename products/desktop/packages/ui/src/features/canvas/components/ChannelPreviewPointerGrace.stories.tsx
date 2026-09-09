import { PreviewCard } from "@base-ui/react/preview-card";
import {
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Text,
} from "@posthog/quill";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useRef } from "react";
import { ChannelPreviewPointerGrace } from "./ChannelPreviewPointerGrace";

const meta = {
  title: "Canvas/ChannelPreviewPointerGrace",
  component: ChannelPreviewPointerGrace,
} satisfies Meta<typeof ChannelPreviewPointerGrace>;

export default meta;
type Story = StoryObj<typeof meta>;

export const PreviewCardCorridor: Story = {
  render: () => {
    const triggerRef = useRef<HTMLElement | null>(null);
    const positionerRef = useRef<HTMLDivElement | null>(null);

    return (
      <PreviewCard.Root>
        <div className="flex w-48 flex-col items-stretch gap-1">
          <PreviewCard.Trigger
            ref={triggerRef}
            delay={0}
            closeDelay={0}
            render={<Button variant="outline" data-channel-preview-trigger />}
          >
            Hover for details
          </PreviewCard.Trigger>
          <Button variant="default" data-channel-preview-trigger>
            Nearby row
          </Button>
          <Button variant="default" data-channel-preview-trigger>
            Another nearby row
          </Button>
        </div>
        <PreviewCard.Portal>
          <ChannelPreviewPointerGrace
            triggerRef={triggerRef}
            floatingRef={positionerRef}
          />
          <PreviewCard.Positioner
            ref={positionerRef}
            side="right"
            sideOffset={24}
            align="start"
            className="z-50"
          >
            <PreviewCard.Popup render={<Card className="w-64" />}>
              <CardHeader>
                <CardTitle>Preview details</CardTitle>
              </CardHeader>
              <CardContent>
                <Text size="sm">
                  Move diagonally from the trigger to this card.
                </Text>
              </CardContent>
            </PreviewCard.Popup>
          </PreviewCard.Positioner>
        </PreviewCard.Portal>
      </PreviewCard.Root>
    );
  },
} satisfies Story;
