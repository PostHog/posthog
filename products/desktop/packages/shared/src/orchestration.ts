import { z } from "zod";
import { piToolCallRecordSchema } from "./pi-tool-call";

export const agentRunStateSchema = z.enum([
  "running",
  "completed",
  "failed",
  "aborted",
]);
export type AgentRunState = z.infer<typeof agentRunStateSchema>;

export const piSubagentToolCallSchema = piToolCallRecordSchema;
export type PiSubagentToolCall = z.infer<typeof piSubagentToolCallSchema>;

export const piSubagentRunDetailsSchema = z.object({
  runId: z.string().optional(),
  agent: z.string(),
  task: z.string(),
  description: z.string().optional(),
  toolCalls: z.array(piSubagentToolCallSchema).optional(),
  state: agentRunStateSchema.optional(),
  exitCode: z.number().optional(),
  model: z.string().optional(),
  stopReason: z.string().optional(),
  errorMessage: z.string().optional(),
  resultText: z.string().optional(),
});

export const piSubagentToolDetailsSchema = z.object({
  mode: z.enum(["single", "parallel"]),
  results: z.array(piSubagentRunDetailsSchema),
});
export type PiSubagentToolDetails = z.infer<typeof piSubagentToolDetailsSchema>;

export const workflowAgentStateSchema = z.enum([
  "running",
  "done",
  "error",
  "aborted",
]);
export type WorkflowAgentState = z.infer<typeof workflowAgentStateSchema>;

export const piWorkflowAgentDetailsSchema = z.object({
  id: z.union([z.number(), z.string()]),
  label: z.string(),
  agent: z.string(),
  status: workflowAgentStateSchema,
  phase: z.string().optional(),
  objective: z.string().optional(),
  produces: z.string().optional(),
  resultPreview: z.string().optional(),
  toolCalls: z.array(piSubagentToolCallSchema).optional(),
});

export const piWorkflowToolDetailsSchema = z.object({
  name: z.string().optional(),
  phases: z.array(z.string()).optional(),
  currentPhase: z.string().optional(),
  done: z.boolean().optional(),
  cancelled: z.boolean().optional(),
  agents: z.array(piWorkflowAgentDetailsSchema),
});
export type PiWorkflowToolDetails = z.infer<typeof piWorkflowToolDetailsSchema>;
