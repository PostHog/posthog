import { z } from "zod";

export const contextWikiPageProposalSchema = z.object({
  id: z.string(),
  task_id: z.string(),
  path: z.string(),
  original_content: z.string(),
  content: z.string(),
  base_head: z.string(),
  created_at: z.string(),
});

export type ContextWikiPageProposal = z.infer<
  typeof contextWikiPageProposalSchema
>;

export const contextWikiProposalsSchema = z.array(
  contextWikiPageProposalSchema,
);

export const contextWikiProposalApplyResultSchema = z.object({
  head_sha: z.string(),
});

export type ContextWikiProposalApplyResult = z.infer<
  typeof contextWikiProposalApplyResultSchema
>;
