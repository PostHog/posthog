import { z } from "zod";

export const feedbackScreenshotOutput = z.string().max(350_000).nullable();

export const feedbackLogsOutput = z.string().max(20_000).nullable();
