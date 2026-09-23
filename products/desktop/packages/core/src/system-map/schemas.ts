import { z } from "zod";

export const SYSTEM_MAP_FLAG = "posthog-desktop-system-map";

const id = z
  .string()
  .min(1)
  .max(80)
  .regex(/^[a-zA-Z0-9_-]+$/);
const path = z
  .string()
  .min(1)
  .max(500)
  .refine(
    (value) =>
      !value.startsWith("/") &&
      !value.includes("\\") &&
      !value.includes(":") &&
      !value
        .split("/")
        .some((part) => part === ".." || part === "." || part === ""),
    "Use a path relative to the repository.",
  );
const evidenceSchema = z.object({
  path,
  line: z.number().int().positive(),
  note: z.string().min(1).max(400),
});

export const systemMapOutputSchema = z.object({
  summary: z.string().min(1).max(1000),
  areas: z
    .array(
      z.object({
        id,
        name: z.string().min(1).max(80),
        summary: z.string().min(1).max(500),
        components: z
          .array(
            z.object({
              id,
              name: z.string().min(1).max(80),
              summary: z.string().min(1).max(500),
              evidence: z.array(evidenceSchema).min(1).max(5),
            }),
          )
          .min(1)
          .max(8),
      }),
    )
    .min(1)
    .max(12),
  relationships: z
    .array(
      z.object({
        source: id,
        target: id,
        kind: z.enum(["imports", "calls", "data", "event"]),
        summary: z.string().min(1).max(500),
        evidence: z.array(evidenceSchema).min(1).max(5),
      }),
    )
    .max(160),
  limitations: z.array(z.string().min(1).max(500)).max(10),
});

export const systemMapSchema = systemMapOutputSchema.superRefine((map, ctx) => {
  const ids = new Set<string>();
  const componentIds = new Set<string>();
  for (const area of map.areas) {
    for (const item of [area, ...area.components]) {
      if (ids.has(item.id))
        ctx.addIssue({ code: "custom", message: `Duplicate ID: ${item.id}` });
      ids.add(item.id);
    }
    for (const component of area.components) componentIds.add(component.id);
  }
  for (const link of map.relationships) {
    if (
      !componentIds.has(link.source) ||
      !componentIds.has(link.target) ||
      link.source === link.target
    ) {
      ctx.addIssue({
        code: "custom",
        message: "A relationship must connect two different components.",
      });
    }
  }
});

export type SystemMap = z.infer<typeof systemMapSchema>;
export type SystemMapArea = SystemMap["areas"][number];
export type SystemMapComponent = SystemMapArea["components"][number];
export type SystemMapEvidence = z.infer<typeof evidenceSchema>;
