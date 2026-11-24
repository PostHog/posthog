import { z } from "zod";
import { GATEWAY_PRODUCTS, type GatewayProduct } from "../../utils/gateway";

export interface RunPolicy {
  readonly finishTool: boolean;
  /** A workflow run that opts into `finish` hands its report to the next step. */
  readonly finishReportRequired: boolean;
  readonly reportActivityTool: boolean;
  readonly expectsSystemPrompt: boolean;
  readonly threadLink: boolean;
  readonly defaultClientProvenance: string | undefined;
  readonly billingProduct: GatewayProduct | undefined;
}

export interface ServerRunPolicy {
  readonly runId: string;
  readonly policy: RunPolicy;
}

const serverRunPolicySchema = z.object({
  run_id: z.string(),
  finish_tool: z.boolean(),
  finish_report_required: z.boolean(),
  report_activity_tool: z.boolean(),
  expects_system_prompt: z.boolean(),
  thread_link: z.boolean(),
  default_client_provenance: z.string().nullable(),
  billing_product: z.enum(GATEWAY_PRODUCTS).optional().catch(undefined),
});

export function parseServerRunPolicy(raw: string): ServerRunPolicy | undefined {
  let payload: unknown;
  try {
    payload = JSON.parse(raw);
  } catch {
    return undefined;
  }
  const parsed = serverRunPolicySchema.safeParse(payload);
  if (!parsed.success) {
    return undefined;
  }
  const policy: RunPolicy = {
    finishTool: parsed.data.finish_tool,
    finishReportRequired: parsed.data.finish_report_required,
    reportActivityTool: parsed.data.report_activity_tool,
    expectsSystemPrompt: parsed.data.expects_system_prompt,
    threadLink: parsed.data.thread_link,
    defaultClientProvenance: parsed.data.default_client_provenance ?? undefined,
    billingProduct: parsed.data.billing_product,
  };
  return { runId: parsed.data.run_id, policy };
}

export const RESTRICTIVE_RUN_POLICY: RunPolicy = {
  finishTool: false,
  finishReportRequired: false,
  reportActivityTool: false,
  expectsSystemPrompt: false,
  threadLink: false,
  defaultClientProvenance: undefined,
  billingProduct: undefined,
};
