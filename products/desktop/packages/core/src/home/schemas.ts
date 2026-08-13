import type { UserBasic } from "@posthog/shared/domain-types";
import { z } from "zod";

/**
 * Where a piece of work stands, across every kind of work a project holds.
 * Deliberately one vocabulary rather than per-kind ones: the home table's whole
 * point is that a session, a canvas, a plan and a todo line up in the same
 * column, so a reader can scan a space's work without translating between three
 * sets of words.
 *
 * `failed` is ours, not Linear's. An agent run that died is the row a reader
 * most needs to see, and folding it into `canceled` hides it among the work
 * somebody deliberately stopped.
 */
export const homeStatusSchema = z.enum([
  "backlog",
  "todo",
  "in_progress",
  "done",
  "failed",
  "canceled",
]);
export type HomeStatus = z.infer<typeof homeStatusSchema>;

/**
 * Group order for the table: what wants attention first, what is finished last.
 * Failures lead because they are the only status that asks the reader to do
 * something they don't already know about.
 */
export const HOME_STATUS_ORDER: readonly HomeStatus[] = [
  "failed",
  "in_progress",
  "todo",
  "backlog",
  "done",
  "canceled",
];

export const HOME_STATUS_LABELS: Record<HomeStatus, string> = {
  backlog: "Backlog",
  todo: "Todo",
  in_progress: "In progress",
  done: "Done",
  failed: "Failed",
  canceled: "Canceled",
};

/** The four things a project holds. */
export const homeWorkKindSchema = z.enum(["session", "canvas", "plan", "todo"]);
export type HomeWorkKind = z.infer<typeof homeWorkKindSchema>;

export const HOME_WORK_KIND_LABELS: Record<HomeWorkKind, string> = {
  session: "Session",
  canvas: "Canvas",
  plan: "Plan",
  todo: "Todo",
};

/**
 * Enough of a `UserBasic` to draw an avatar and a name, stored on the records
 * this app owns so a plan filed months ago still says who wrote it without a
 * lookup against the org's member list.
 */
export const homeUserSchema = z.object({
  id: z.number(),
  uuid: z.string(),
  email: z.string(),
  first_name: z.string().optional(),
  last_name: z.string().optional(),
}) satisfies z.ZodType<UserBasic>;

/**
 * A project: the unit of work inside a space. It holds sessions and canvases
 * that already exist in the space, plus plans and todos authored here.
 *
 * `spaceId` is a backend channel id — a project cannot exist outside a space,
 * because the space is what decides who can see the work it gathers.
 */
export const homeProjectSchema = z.object({
  id: z.string().min(1),
  spaceId: z.string().min(1),
  name: z.string().min(1),
  status: homeStatusSchema,
  /** Who is driving it; null while nobody has claimed it. */
  lead: homeUserSchema.nullable(),
  createdAt: z.number(),
  updatedAt: z.number(),
});
export type HomeProject = z.infer<typeof homeProjectSchema>;

/**
 * A plan or a todo — the two kinds of work a project holds that are authored
 * here rather than filed from something the backend already owns. Both are the
 * same record because they differ only in how much prose they carry: a todo is
 * a line, a plan is a document.
 */
export const homeNoteSchema = z.object({
  id: z.string().min(1),
  projectId: z.string().min(1),
  kind: z.enum(["plan", "todo"]),
  title: z.string(),
  /** Markdown. Empty for a todo that is just its title. */
  body: z.string(),
  status: homeStatusSchema,
  /** Whoever is carrying it; null until someone picks it up. */
  assignee: homeUserSchema.nullable(),
  createdAt: z.number(),
  updatedAt: z.number(),
});
export type HomeNote = z.infer<typeof homeNoteSchema>;

/**
 * Which project a session or canvas belongs to, keyed by the work's own id.
 * Filing is a client-side relation for now, so it is stored beside the projects
 * rather than on the task or canvas record itself.
 */
export const homeFilingSchema = z.record(z.string(), z.string());
export type HomeFiling = z.infer<typeof homeFilingSchema>;

/**
 * Everything the projects layer holds, as one persisted shape. Kept together
 * because the three parts only make sense as a set: a note without its project
 * has nowhere to live, and a filing pointing at a deleted project is a row that
 * claims a parent it doesn't have.
 */
export const homeRegistrySchema = z.object({
  projects: z.record(z.string(), homeProjectSchema),
  notes: z.record(z.string(), homeNoteSchema),
  filing: homeFilingSchema,
});
export type HomeRegistry = z.infer<typeof homeRegistrySchema>;
