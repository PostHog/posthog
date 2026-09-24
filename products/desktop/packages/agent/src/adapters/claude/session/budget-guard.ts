import type { HookCallback, HookInput } from "@anthropic-ai/claude-agent-sdk";
import type { Logger } from "../../../utils/logger";

export const BUDGET_CAP_ENV = "AI_GATEWAY_TOKEN_CAP_USD";
export const BUDGET_PRICES_ENV = "AI_GATEWAY_MODEL_PRICES_JSON";
export const BUDGET_WARN_RATIO = 0.5;
export const BUDGET_CRITICAL_RATIO = 0.7;
export const FAST_MODE_PRICE_MULTIPLIER = 2;
export const ONE_HOUR_CACHE_WRITE_INPUT_MULTIPLIER = 2;

export type BudgetStage = "ok" | "warn" | "critical";
export type BudgetSteerStage = Exclude<BudgetStage, "ok">;
export type BudgetSteerMode = "publish" | "wrap_up";
export type BudgetSpendSource = "main" | "side";

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
  stage: BudgetSteerStage;
  spentUsd: number;
  capUsd: number;
}

export interface BudgetSteerRecord {
  stage: BudgetSteerStage;
  spent_usd: number;
  threshold_spent_usd: number;
  threshold_at: string;
  delivered_at: string | null;
  delivered: boolean;
}

export interface BudgetGuardSnapshot {
  cap_usd: number;
  spent_usd: number;
  estimated_usd: number;
  sdk_total_usd: number;
  stage: BudgetStage;
  mode: BudgetSteerMode;
  steers: BudgetSteerRecord[];
}

export interface AssistantUsageLike {
  id?: string | null;
  model?: string | null;
  usage?: {
    input_tokens?: number | null;
    output_tokens?: number | null;
    cache_read_input_tokens?: number | null;
    cache_creation_input_tokens?: number | null;
    cache_creation?: {
      ephemeral_1h_input_tokens?: number | null;
      ephemeral_5m_input_tokens?: number | null;
    } | null;
    speed?: string | null;
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
  {
    match: /glm-[\d.]+-flash/i,
    price: { input: 0.15, output: 0.5, cacheRead: 0.03, cacheWrite: 0.15 },
  },
  {
    match: /glm/i,
    price: { input: 1.4, output: 4.4, cacheRead: 0.14, cacheWrite: 1.4 },
  },
  {
    match: /kimi/i,
    price: { input: 3, output: 15, cacheRead: 0.3, cacheWrite: 3 },
  },
  {
    match: /deepseek/i,
    price: { input: 0.13, output: 0.26, cacheRead: 0.028, cacheWrite: 0.13 },
  },
];

const CRITICAL_BLOCKED_TOOL_NAMES = new Set([
  "Agent",
  "Task",
  "Workflow",
  "WebFetch",
  "WebSearch",
]);

const STAGE_RANK: Record<BudgetStage, number> = { ok: 0, warn: 1, critical: 2 };

function isPrice(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

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
        !isPrice(price?.input) ||
        !isPrice(price.output) ||
        !isPrice(price.cacheRead) ||
        !isPrice(price.cacheWrite)
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
  const cacheWriteTotal = usage.cache_creation_input_tokens ?? 0;
  const oneHourWrites = Math.min(
    usage.cache_creation?.ephemeral_1h_input_tokens ?? 0,
    cacheWriteTotal,
  );
  const fiveMinuteWrites = cacheWriteTotal - oneHourWrites;
  const base =
    ((usage.input_tokens ?? 0) * price.input +
      (usage.output_tokens ?? 0) * price.output +
      (usage.cache_read_input_tokens ?? 0) * price.cacheRead +
      fiveMinuteWrites * price.cacheWrite +
      oneHourWrites * price.input * ONE_HOUR_CACHE_WRITE_INPUT_MULTIPLIER) /
    1_000_000;
  return usage.speed === "fast" ? base * FAST_MODE_PRICE_MULTIPLIER : base;
}

function formatUsd(value: number): string {
  return `$${value.toFixed(2)}`;
}

export class RunBudgetGuard {
  private readonly perMessageUsd = new Map<string, number>();
  private estimatedUsd = 0;
  private sideUsd = 0;
  private sdkBaseUsd = 0;
  private sdkTotalUsd = 0;
  private estimatedAtSdkTotal = 0;
  private stage: BudgetStage = "ok";
  private readonly thresholds = new Map<
    BudgetSteerStage,
    { spentUsd: number; at: string }
  >();
  private deliveredStage: BudgetStage = "ok";
  private pendingSteer: BudgetSteerStage | null = null;
  private steerMode: BudgetSteerMode;
  private readonly steers: BudgetSteerRecord[] = [];

  constructor(
    readonly capUsd: number,
    private readonly prices: readonly ModelPriceRule[],
    private readonly logger: Logger,
    mode: BudgetSteerMode = "wrap_up",
    private readonly warnRatio: number = BUDGET_WARN_RATIO,
    private readonly criticalRatio: number = BUDGET_CRITICAL_RATIO,
  ) {
    this.steerMode = mode;
  }

  static fromEnv(
    env: NodeJS.ProcessEnv,
    logger: Logger,
    mode: BudgetSteerMode = "wrap_up",
  ): RunBudgetGuard | null {
    const capUsd = Number.parseFloat(env[BUDGET_CAP_ENV] ?? "");
    if (!Number.isFinite(capUsd) || capUsd <= 0) return null;
    const prices =
      parseModelPricesJson(env[BUDGET_PRICES_ENV], logger) ??
      DEFAULT_MODEL_PRICES;
    return new RunBudgetGuard(capUsd, prices, logger, mode);
  }

  get mode(): BudgetSteerMode {
    return this.steerMode;
  }

  setMode(mode: BudgetSteerMode): void {
    if (mode === this.steerMode) return;
    this.logger.info("[BudgetGuard] Steer mode changed", {
      from: this.steerMode,
      to: mode,
    });
    this.steerMode = mode;
  }

  get spentUsd(): number {
    const mainEstimatedUsd = this.estimatedUsd - this.sideUsd;
    const calibrated =
      this.sdkBaseUsd +
      this.sdkTotalUsd +
      this.sideUsd +
      Math.max(0, mainEstimatedUsd - this.estimatedAtSdkTotal);
    return Math.max(this.estimatedUsd, calibrated);
  }

  get ratio(): number {
    return this.spentUsd / this.capUsd;
  }

  get currentStage(): BudgetStage {
    return this.stage;
  }

  recordAssistantMessage(
    message: AssistantUsageLike,
    source: BudgetSpendSource = "main",
  ): BudgetThresholdEvent | null {
    const cost = estimateMessageCostUsd(message, this.prices);
    let added = cost;
    if (message.id) {
      const previous = this.perMessageUsd.get(message.id) ?? 0;
      if (cost <= previous) return this.advanceStage();
      this.perMessageUsd.set(message.id, cost);
      added = cost - previous;
    }
    this.estimatedUsd += added;
    if (source === "side") this.sideUsd += added;
    return this.advanceStage();
  }

  calibrate(totalCostUsd: number | undefined): BudgetThresholdEvent | null {
    if (typeof totalCostUsd !== "number" || !Number.isFinite(totalCostUsd)) {
      return null;
    }
    if (totalCostUsd < this.sdkTotalUsd) {
      this.logger.debug("[BudgetGuard] Ignoring a lower SDK running total", {
        totalCostUsd,
        sdkTotalUsd: this.sdkTotalUsd,
      });
      return this.advanceStage();
    }
    this.sdkTotalUsd = totalCostUsd;
    this.estimatedAtSdkTotal = this.estimatedUsd - this.sideUsd;
    return this.advanceStage();
  }

  onQueryReset(): void {
    this.sdkBaseUsd += this.sdkTotalUsd;
    this.sdkTotalUsd = 0;
    this.estimatedAtSdkTotal = this.estimatedUsd - this.sideUsd;
  }

  onConversationCleared(): void {
    this.onQueryReset();
    this.deliveredStage = "ok";
    if (this.stage !== "ok") this.pendingSteer = this.stage;
  }

  takePendingSteer(): BudgetSteerStage | null {
    const stage = this.pendingSteer;
    this.pendingSteer = null;
    return stage;
  }

  markUndelivered(stage: BudgetSteerStage): void {
    if (STAGE_RANK[stage] <= STAGE_RANK[this.deliveredStage]) return;
    if (
      this.pendingSteer === null ||
      STAGE_RANK[stage] > STAGE_RANK[this.pendingSteer]
    ) {
      this.pendingSteer = stage;
    }
  }

  recordSteer(stage: BudgetSteerStage, delivered: boolean): BudgetSteerRecord {
    const spent = this.spentUsd;
    const deliveredAt = new Date().toISOString();
    const threshold = this.thresholds.get(stage);
    const record = {
      stage,
      spent_usd: spent,
      threshold_spent_usd: threshold?.spentUsd ?? spent,
      threshold_at: threshold?.at ?? deliveredAt,
      delivered_at: delivered ? deliveredAt : null,
      delivered,
    };
    this.steers.push(record);
    if (delivered && STAGE_RANK[stage] > STAGE_RANK[this.deliveredStage]) {
      this.deliveredStage = stage;
    }
    return record;
  }

  snapshot(): BudgetGuardSnapshot {
    return {
      cap_usd: this.capUsd,
      spent_usd: this.spentUsd,
      estimated_usd: this.estimatedUsd,
      sdk_total_usd: this.sdkBaseUsd + this.sdkTotalUsd,
      stage: this.stage,
      mode: this.mode,
      steers: [...this.steers],
    };
  }

  steerText(stage: BudgetSteerStage): string {
    const spent = formatUsd(this.spentUsd);
    const cap = formatUsd(this.capUsd);
    if (this.mode === "publish") {
      if (stage === "critical") {
        return (
          `Budget critical: this run has used about ${spent} of its ${cap} model budget. ` +
          "The gateway will refuse further calls very soon and everything uncommitted is lost then. " +
          "Stop new work now. Stage what is on disk and commit it with the git_signed_commit tool " +
          "(it publishes the commit for you; raw git commit and git push are blocked here), then open " +
          "or update the pull request and end your turn with a two-line summary. " +
          "Do not start subagents or workflows, and do not run further test or review passes."
        );
      }
      return (
        `Budget notice: this run has used about ${spent} of its ${cap} model budget. ` +
        "Wrap up now. Finish the smallest coherent version of the change, run only the tests you " +
        "already touched, then stage and commit with the git_signed_commit tool (it publishes the " +
        "commit for you; raw git commit and git push are blocked here) and open the draft pull request. " +
        "Skip optional polish such as /simplify or parallel review subagents: an open PR is what " +
        "preserves the work. If a PR is already open, commit what you have and stop."
      );
    }
    const explicitPr =
      "If the user asked you to open or update a pull request, commit what is on disk with the " +
      "git_signed_commit tool and do that first. ";
    if (stage === "critical") {
      return (
        `Budget critical: this run has used about ${spent} of its ${cap} model budget. ` +
        "The gateway will refuse further calls very soon. Stop new work now. " +
        explicitPr +
        "Then end your turn with your result so far: what is done, what is not, and what you found. " +
        "Do not start subagents or workflows, and do not read or run anything else."
      );
    }
    return (
      `Budget notice: this run has used about ${spent} of its ${cap} model budget. ` +
      "Wrap up now. Finish the step you are on, then give your result with what you have. " +
      explicitPr +
      "Skip further exploration, optional checks, and parallel subagents."
    );
  }

  preToolUseHook(): HookCallback {
    return async (input: HookInput) => {
      if (input.hook_event_name !== "PreToolUse") return { continue: true };
      if (!CRITICAL_BLOCKED_TOOL_NAMES.has(input.tool_name)) {
        return { continue: true };
      }
      if (this.stage !== "critical") return { continue: true };
      this.logger.warn(
        `[BudgetGuard] Blocking ${input.tool_name} at ${formatUsd(this.spentUsd)} of ${formatUsd(this.capUsd)}`,
      );
      const next =
        this.mode === "publish"
          ? "Commit what is on disk with the git_signed_commit tool and open or update the pull request yourself."
          : "Finish with the result you have.";
      return {
        continue: true,
        hookSpecificOutput: {
          hookEventName: "PreToolUse" as const,
          permissionDecision: "deny" as const,
          permissionDecisionReason:
            `This run has used about ${formatUsd(this.spentUsd)} of its ${formatUsd(this.capUsd)} model budget, ` +
            `so no new subagents, workflows, or web lookups can start. ${next}`,
        },
      };
    };
  }

  private advanceStage(): BudgetThresholdEvent | null {
    const ratio = this.ratio;
    let next: BudgetStage = "ok";
    if (ratio >= this.criticalRatio) next = "critical";
    else if (ratio >= this.warnRatio) next = "warn";
    if (next === "ok" || next === this.stage || this.stage === "critical") {
      return null;
    }
    this.stage = next;
    this.pendingSteer = next;
    const spentUsd = this.spentUsd;
    this.thresholds.set(next, { spentUsd, at: new Date().toISOString() });
    return { stage: next, spentUsd, capUsd: this.capUsd };
  }
}
