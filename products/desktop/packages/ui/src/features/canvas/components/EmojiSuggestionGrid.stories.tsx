import type { EmojiSuggestion } from "@posthog/ui/features/canvas/utils/emojiSuggestions";
import type { Meta, StoryObj } from "@storybook/react";
import { type ReactElement, useState } from "react";
import { EmojiSuggestionGrid } from "./EmojiSuggestionGrid";

const suggestions: EmojiSuggestion[] = [
  {
    id: "unicode:👋",
    name: "wave",
    keywords: ["wave", "hello"],
    insertion: "👋",
    emoji: "👋",
  },
  {
    id: "unicode:🎉",
    name: "tada",
    keywords: ["tada", "party"],
    insertion: "🎉",
    emoji: "🎉",
  },
  {
    id: "unicode:🔥",
    name: "fire",
    keywords: ["fire"],
    insertion: "🔥",
    emoji: "🔥",
  },
  {
    id: "unicode:🚀",
    name: "rocket",
    keywords: ["rocket"],
    insertion: "🚀",
    emoji: "🚀",
  },
  {
    id: "unicode:❤️",
    name: "heart",
    keywords: ["heart"],
    insertion: "❤️",
    emoji: "❤️",
  },
  {
    id: "unicode:👍",
    name: "thumbs_up",
    keywords: ["thumbs_up", "+1"],
    insertion: "👍",
    emoji: "👍",
  },
];

const meta = {
  title: "Canvas/Emoji suggestion grid",
  component: EmojiSuggestionGrid,
  decorators: [
    (Story): ReactElement => (
      <div className="relative mt-64 w-80">
        <Story />
      </div>
    ),
  ],
} satisfies Meta<typeof EmojiSuggestionGrid>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  render: (): ReactElement => {
    const [highlightedIndex, setHighlightedIndex] = useState(0);
    return (
      <EmojiSuggestionGrid
        suggestions={suggestions}
        highlightedIndex={highlightedIndex}
        onHighlight={setHighlightedIndex}
        onSelect={() => undefined}
      />
    );
  },
};
