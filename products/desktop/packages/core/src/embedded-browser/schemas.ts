import { z } from "zod";

export const embeddedBrowserBoundsSchema = z.object({
  x: z.number(),
  y: z.number(),
  width: z.number().nonnegative(),
  height: z.number().nonnegative(),
});

export const openEmbeddedBrowserInput = z.object({
  viewId: z.string().min(1),
  url: z.string().min(1),
  bounds: embeddedBrowserBoundsSchema,
});

export const navigateEmbeddedBrowserInput = z.object({
  viewId: z.string().min(1),
  url: z.string().min(1),
});

export const embeddedBrowserViewIdInput = z.object({
  viewId: z.string().min(1),
});

export const setEmbeddedBrowserBoundsInput = z.object({
  viewId: z.string().min(1),
  bounds: embeddedBrowserBoundsSchema,
});

export const setEmbeddedBrowserVisibleInput = z.object({
  viewId: z.string().min(1),
  visible: z.boolean(),
});

export const embeddedBrowserPageStateSchema = z.object({
  viewId: z.string(),
  url: z.string(),
  title: z.string(),
  canGoBack: z.boolean(),
  canGoForward: z.boolean(),
  isLoading: z.boolean(),
});
