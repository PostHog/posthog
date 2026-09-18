import type { HookCallback, HookInput } from "@anthropic-ai/claude-agent-sdk";
import type { Logger } from "../../../utils/logger";

export const BUDGET_CAP_ENV = "AI_GATEWAY_TOKEN_CAP_USD";
export const BUDGET_PRICES_ENV = "AI_GATEWAY_MODEL_PRICES_JSON";
export const BUDGET_WARN_RATIO = 0.7;
export const BUDGET_CRITICAL_RATIO = 0.85;

export type BudgetStage = "ok" | "warn" | "critical";

export interface ModelPrice {
  input: number;
  output: number;
  cacheRead: number;
  cacheWrite: number;
}

export interface ModelPriceRule {
  match: RegExp;
  price: ModelPrice;
}

export interface BudgetThresholdEvent {
  stage: Exclude<BudgetStage, "ok">;
  spentUsd: number;
  capUsd: number;
}

export interface AssistantUsageLike {
  id?: string | null;
  model?: string | null;
  usage?: {
    input_tokens?: number | null;
    output_tokens?: number | null;
    cache_read_input_tokens?: number | null;
    cache_creation_input_tokens?: number | null;
  } | null;
}

const OPUS_PRICE: ModelPrice = {
  input: 5,
  output: 25,
  cacheRead: 0.5,
  cacheWrite: 6.25,
};

export const DEFAULT_MODEL_PRICES: readonly ModelPriceRule[] = [
  {
    match: /fable|mythos/i,
    price: { input: 10, output: 50, cacheRead: 1, cacheWrite: 12.5 },
  },
  { match: /opus/i, price: OPUS_PRICE },
  {
    match: /sonnet-5/i,
    price: { input: 2, output: 10, cacheRead: 0.2, cacheWrite: 2.5 },
  },
  {
    match: /sonnet/i,
    price: { input: 3, output: 15, cacheRead: 0.3, cacheWrite: 3.75 },
  },
  {
    match: /haiku/i,
    price: { input: 1, output: 5, cacheRead: 0.1, cacheWrite: 1.25 },
  },
];

const SUBAGENT_TOOL_NAMES = new Set(["Agent", "Task"]);

export function parseModelPricesJson(
  raw: string | undefined,
  logger: Logger,
): ModelPriceRule[] | null {
  if (!raw?.trim()) return null;
  try {
    const parsed = JSON.parse(raw) as Record<string, Partial<ModelPrice>>;
    const rules: ModelPriceRule[] = [];
    for (const [pattern, price] of Object.entries(parsed)) {
      if (
        typeof price?.input !== "number" ||
        typeof price.output !== "number" ||
        typeof price.cacheRead !== "number" ||
        typeof price.cacheWrite !== "number"
      ) {
        continue;
      }
      rules.push({
        match: new RegExp(pattern, "i"),
        price: {
          input: price.input,
          output: price.output,
          cacheRead: price.cacheRead,
          cacheWrite: price.cacheWrite,
        },
      });
    }
    return rules.length > 0 ? rules : null;
  } catch (error) {
    logger.warn(`[BudgetGuard] Ignoring invalid ${BUDGET_PRICES_ENV}`, {
      error,
    });
    return null;
  }
}

export function estimateMessageCostUsd(
  message: AssistantUsageLike,
  prices: readonly ModelPriceRule[],
): number {
  const usage = message.usage;
  if (!usage) return 0;
  const model = message.model ?? "";
  const price =
    prices.find((rule) => rule.match.test(model))?.price ?? OPUS_PRICE;
  return (
    ((usage.input_tokens ?? 0) * price.input +
      (usage.output_tokens ?? 0) * price.output +
      (usage.cache_read_input_tokens ?? 0) * price.cacheRead +
      (usage.cache_creation_input_tokens ?? 0) * price.cacheWrite) /
    1_000_000
  );
}

function formatUsd(value: number): string {
  return `$${value.toFixed(2)}`;
}

export class RunBudgetGuard {
  private readonly perMessageUsd = new Map<string, number>();
  private estimatedUsd = 0;
  private sdkTotalUsd = 0;
  private estimatedAtSdkTotal = 0;
  private stage: BudgetStage = "ok";

  constructor(
    readonly capUsd: number,
    private readonly prices: readonly ModelPriceRule[],
    private readonly logger: Logger,
    private readonly warnRatio: number = BUDGET_WARN_RATIO,
    private readonly criticalRatio: number = BUDGET_CRITICAL_RATIO,
  ) {}

  static fromEnv(
    env: NodeJS.ProcessEnv,
    logger: Logger,
  ): RunBudgetGuard | null {
    const capUsd = Number.parseFloat(env[BUDGET_CAP_ENV] ?? "");
    if (!Number.isFinite(capUsd) || capUsd <= 0) return null;
    const prices =
      parseModelPricesJson(env[BUDGET_PRICES_ENV], logger) ??
      DEFAULT_MODEL_PRICES;
    return new RunBudgetGuard(capUsd, prices, logger);
  }

  get spentUsd(): number {
    return (
      this.sdkTotalUsd +
      Math.max(0, this.estimatedUsd - this.estimatedAtSdkTotal)
    );
  }

  get ratio(): number {
    return this.spentUsd / this.capUsd;
  }

  get currentStage(): BudgetStage {
    return this.stage;
  }

  recordAssistantMessage(
    message: AssistantUsageLike,
  ): BudgetThresholdEvent | null {
    const cost = estimateMessageCostUsd(message, this.prices);
    if (message.id) {
      const previous = this.perMessageUsd.get(message.id) ?? 0;
      if (cost <= previous) return this.advanceStage();
      this.perMessageUsd.set(message.id, cost);
      this.estimatedUsd += cost - previous;
    } else {
      this.estimatedUsd += cost;
    }
    return this.advanceStage();
  }

  calibrate(totalCostUsd: number | undefined): BudgetThresholdEvent | null {
    if (
      typeof totalCostUsd !== "number" ||
      !Number.isFinite(totalCostUsd) ||
      totalCostUsd < this.sdkTotalUsd
    ) {
      return null;
    }
    this.sdkTotalUsd = totalCostUsd;
    this.estimatedAtSdkTotal = this.estimatedUsd;
    return this.advanceStage();
  }

  steerText(stage: Exclude<BudgetStage, "ok">): string {
    const spent = formatUsd(this.spentUsd);
    const cap = formatUsd(this.capUsd);
    if (stage === "critical") {
      return (
        `Budget critical: this run has used about ${spent} of its ${cap} model budget. ` +
        "The gateway will refuse further calls very soon and everything uncommitted is lost then. " +
        "Stop new work now. Stage what is on disk, commit it with the git_signed_commit tool, push, " +
        "and open or update the pull request, then end your turn with a two-line summary. " +
        "Do not start subagents, do not run further test or review passes."
      );
    }
    return (
      `Budget notice: this run has used about ${spent} of its ${cap} model budget. ` +
      "Wrap up now. Finish the smallest coherent version of the change, run only the tests you " +
      "already touched, then stage, commit with the git_signed_commit tool, push, and open the draft " +
      "pull request. Skip optional polish such as /simplify or parallel review subagents: an open PR " +
      "is what preserves the work. If a PR is already open, push what you have and stop."
    );
  }

  preToolUseHook(): HookCallback {
    return async (input: HookInput) => {
      if (input.hook_event_name !== "PreToolUse") return { continue: true };
      if (!SUBAGENT_TOOL_NAMES.has(input.tool_name)) return { continue: true };
      if (this.stage !== "critical") return { continue: true };
      this.logger.warn(
        `[BudgetGuard] Blocking ${input.tool_name} spawn at ${formatUsd(this.spentUsd)} of ${formatUsd(this.capUsd)}`,
      );
      return {
        continue: true,
        hookSpecificOutput: {
          hookEventName: "PreToolUse" as const,
          permissionDecision: "deny" as const,
          permissionDecisionReason:
            `This run has used about ${formatUsd(this.spentUsd)} of its ${formatUsd(this.capUsd)} model budget, ` +
            "so no new subagents can start. Commit what is on disk with git_signed_commit, push, " +
            "and open or update the pull request yourself.",
        },
      };
    };
  }

  private advanceStage(): BudgetThresholdEvent | null {
    const ratio = this.ratio;
    let next: BudgetStage = "ok";
    if (ratio >= this.criticalRatio) next = "critical";
    else if (ratio >= this.warnRatio) next = "warn";
    if (next === "ok" || next === this.stage) return null;
    if (this.stage === "critical") return null;
    this.stage = next;
    return { stage: next, spentUsd: this.spentUsd, capUsd: this.capUsd };
  }
}
