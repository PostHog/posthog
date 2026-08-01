import { z } from "zod";

export const taskAutomationSchema = z.object({
  id: z.string(),
  name: z.string(),
  prompt: z.string(),
  repository: z.string(),
  github_integration: z.number().nullable().default(null),
  cron_expression: z.string(),
  timezone: z.string().nullable().default(null),
  template_id: z.string().nullable().default(null),
  enabled: z.boolean().default(true),
  last_run_at: z.string().nullable(),
  last_run_status: z.string().nullable(),
  last_task_id: z.string().nullable(),
  last_task_run_id: z.string().nullable(),
  last_error: z.string().nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type TaskAutomation = z.infer<typeof taskAutomationSchema>;

export const taskAutomationListSchema = z.object({
  count: z.number(),
  next: z.string().nullable().optional(),
  previous: z.string().nullable().optional(),
  results: z.array(taskAutomationSchema),
});
export type TaskAutomationList = z.infer<typeof taskAutomationListSchema>;

export const createTaskAutomationSchema = z.object({
  name: z.string(),
  prompt: z.string(),
  repository: z.string(),
  github_integration: z.number().nullable().optional(),
  cron_expression: z.string(),
  timezone: z.string(),
  template_id: z.string().nullable().optional(),
  enabled: z.boolean().optional(),
});
export type CreateTaskAutomationOptions = z.infer<
  typeof createTaskAutomationSchema
>;

export const updateTaskAutomationSchema = createTaskAutomationSchema.partial();
export type UpdateTaskAutomationOptions = z.infer<
  typeof updateTaskAutomationSchema
>;

export const taskAutomationValidationErrorSchema = z.object({
  type: z.string().optional(),
  code: z.string().default("invalid_input"),
  detail: z.string(),
  attr: z.string().nullable().default(null),
});
export type TaskAutomationValidationErrorDetails = z.infer<
  typeof taskAutomationValidationErrorSchema
>;
