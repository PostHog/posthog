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
import { ChannelHoverSafeArea } from "./ChannelHoverSafeArea";

const meta = {
  title: "Canvas/ChannelHoverSafeArea",
  component: ChannelHoverSafeArea,
} satisfies Meta<typeof ChannelHoverSafeArea>;

export default meta;
type Story = StoryObj<typeof meta>;

export const PreviewCardCorridor: Story = {
  render: () => {
    const anchorRef = useRef<HTMLElement | null>(null);
    const positionerRef = useRef<HTMLDivElement | null>(null);

    return (
      <PreviewCard.Root>
        <div className="flex w-48 flex-col items-stretch gap-1">
          <PreviewCard.Trigger
            ref={anchorRef}
            delay={0}
            closeDelay={0}
            render={<Button variant="outline" />}
          >
            Hover for details
          </PreviewCard.Trigger>
          <Button variant="default">Nearby row</Button>
          <Button variant="default">Another nearby row</Button>
        </div>
        <PreviewCard.Portal>
          <ChannelHoverSafeArea
            anchorRef={anchorRef}
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
