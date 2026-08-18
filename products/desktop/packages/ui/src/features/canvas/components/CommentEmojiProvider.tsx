import type { CommentEmoji } from "@posthog/api-client/posthog-client";
import { useCommentEmojis } from "@posthog/ui/features/canvas/hooks/useCommentEmojis";
import {
  createContext,
  type ReactElement,
  type ReactNode,
  useContext,
} from "react";

const CommentEmojiContext = createContext<CommentEmoji[]>([]);

export function CommentEmojiProvider({
  children,
}: {
  children: ReactNode;
}): ReactElement {
  const { data: emojis = [] } = useCommentEmojis();
  return (
    <CommentEmojiContext.Provider value={emojis}>
      {children}
    </CommentEmojiContext.Provider>
  );
}

export function useCommentEmojiList(): CommentEmoji[] {
  return useContext(CommentEmojiContext);
}
