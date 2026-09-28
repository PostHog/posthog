import {
  type EditorContent,
  isContentEmpty,
} from "@posthog/core/message-editor/content";
import { inject, injectable } from "inversify";

export type CommentAgentContext = {
  label: string;
  body: string;
  screenshot?: string;
};

export type CommentSurface = "artifact" | "canvas" | "task";

export interface CommentToAgentHost {
  persistScreenshot(dataUrl: string): Promise<string>;
  getDraft(taskId: string): EditorContent | string | null;
  hasPendingInsert(taskId: string): boolean;
  insertIntoDraft(taskId: string, content: EditorContent): void;
  showTaskChat(taskId: string, options: { focus: boolean }): void;
  trackCommentSent(properties: {
    surface: CommentSurface;
    with_context: boolean;
    with_screenshot: boolean;
  }): void;
}

export const COMMENT_TO_AGENT_HOST = Symbol.for(
  "posthog.core.sessions.commentToAgentHost",
);

export function commentComposerContent({
  comment,
  draftEmpty,
  context,
}: {
  comment: string;
  draftEmpty: boolean;
  context: (CommentAgentContext & { imagePath?: string }) | null;
}): EditorContent {
  const segments: EditorContent["segments"] = [];
  if (!draftEmpty) segments.push({ type: "text", text: "\n" });
  if (context) {
    segments.push(
      {
        type: "chip",
        chip: {
          type: "comment_context",
          id: context.body,
          label: context.label,
          ...(context.imagePath ? { imagePath: context.imagePath } : {}),
        },
      },
      { type: "text", text: " " },
    );
  }
  segments.push({ type: "text", text: comment });
  return { segments };
}

@injectable()
export class CommentToAgentService {
  constructor(
    @inject(COMMENT_TO_AGENT_HOST)
    private readonly host: CommentToAgentHost,
  ) {}

  async send({
    taskId,
    comment,
    context,
    surface,
    openChat = true,
  }: {
    taskId: string;
    comment: string;
    context: CommentAgentContext | null;
    surface: CommentSurface;
    openChat?: boolean;
  }): Promise<void> {
    const imagePath = context?.screenshot
      ? await this.saveScreenshot(context.screenshot)
      : undefined;
    const draftEmpty =
      isContentEmpty(this.host.getDraft(taskId)) &&
      !this.host.hasPendingInsert(taskId);
    this.host.insertIntoDraft(
      taskId,
      commentComposerContent({
        comment,
        draftEmpty,
        context: context ? { ...context, imagePath } : null,
      }),
    );
    if (openChat) this.host.showTaskChat(taskId, { focus: true });
    this.host.trackCommentSent({
      surface,
      with_context: !!context,
      with_screenshot: !!imagePath,
    });
  }

  private async saveScreenshot(dataUrl: string): Promise<string | undefined> {
    try {
      return await this.host.persistScreenshot(dataUrl);
    } catch {
      return undefined;
    }
  }
}
