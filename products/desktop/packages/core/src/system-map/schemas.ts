import { z } from "zod";

export const SYSTEM_MAP_FLAG = "posthog-desktop-system-map";

export const systemMapReferenceSchema = z.object({
  taskId: z.string().uuid(),
  runId: z.string().uuid(),
  analyzedAt: z.string().datetime(),
});

export type SystemMapReference = z.infer<typeof systemMapReferenceSchema>;

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
  coverage: z
    .array(
      z.object({
        path,
        status: z.enum(["reviewed", "partial", "not_reviewed"]),
        summary: z.string().min(1).max(500),
        componentIds: z.array(id).max(96),
      }),
    )
    .min(1)
    .max(100),
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
              operations: z
                .array(
                  z.object({
                    name: z.string().min(1).max(120),
                    kind: z.enum(["query", "command", "unknown"]),
                    summary: z.string().min(1).max(500),
                    evidence: z.array(evidenceSchema).min(1).max(3),
                  }),
                )
                .max(8),
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
        assumptions: z
          .array(
            z.object({
              summary: z.string().min(1).max(500),
              evidence: z.array(evidenceSchema).min(1).max(3),
            }),
          )
          .max(5),
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
  const coveragePaths = new Set<string>();
  for (const [index, scope] of map.coverage.entries()) {
    if (coveragePaths.has(scope.path))
      ctx.addIssue({
        code: "custom",
        path: ["coverage", index, "path"],
        message: "Each source path must have one coverage entry.",
      });
    coveragePaths.add(scope.path);
    if (scope.status === "not_reviewed" && scope.componentIds.length > 0)
      ctx.addIssue({
        code: "custom",
        path: ["coverage", index, "componentIds"],
        message: "Unreviewed source cannot support a component.",
      });
    for (const componentId of scope.componentIds) {
      if (!componentIds.has(componentId))
        ctx.addIssue({
          code: "custom",
          path: ["coverage", index, "componentIds"],
          message: `Unknown component: ${componentId}`,
        });
    }
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
