import { z } from "zod";

export const feedbackLogsOutput = z.string().max(20_000).nullable();

export const feedbackScreenshotOutput = z.string().max(350_000).nullable();

const feedbackImage = z.object({
  name: z.string().min(1).max(1_000),
  dataUrl: z
    .string()
    .max(350_000)
    .regex(/^data:image\/(?:jpeg|png|webp);base64,/),
});

export const feedbackSubmissionInput = z.object({
  response: z.string().trim().min(1).max(4_000),
  source: z.string().min(1).max(100),
  feedbackView: z.string().min(1).max(100),
  feedbackTaskId: z.string().max(100).optional(),
  feedbackFolderId: z.string().max(100).optional(),
  feedbackAppLogs: z.string().max(20_000).optional(),
  sessionId: z.uuid().optional(),
  screenshot: feedbackImage.optional(),
  images: z.array(feedbackImage).max(2),
});
