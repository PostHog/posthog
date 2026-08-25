export const AGENT_BOOT_CONTRACT_VERSION = 1;

export const AGENT_BOOT_PHASES = [
  "context_fetch",
  "acp_initialize",
  "repository_ready",
  "session_dependencies",
  "session_create",
] as const;

export type AgentBootPhase = (typeof AGENT_BOOT_PHASES)[number];
export type AgentBootState = "starting" | "ready" | "failed";

export interface AgentBootSnapshot {
  contractVersion: number;
  bootId: string;
  state: AgentBootState;
  currentPhase?: AgentBootPhase;
  failedPhase?: AgentBootPhase;
  totalMs: number;
  phasesMs: Partial<Record<AgentBootPhase, number>>;
}

export class AgentBootTracker {
  private readonly startedAt = performance.now();
  private state: AgentBootState = "starting";
  private currentPhase?: AgentBootPhase;
  private currentPhaseStartedAt?: number;
  private failedPhase?: AgentBootPhase;
  private totalMs?: number;
  private readonly phasesMs: Partial<Record<AgentBootPhase, number>> = {};

  constructor(private readonly bootId: string) {}

  async measure<T>(phase: AgentBootPhase, work: () => Promise<T>): Promise<T> {
    this.start(phase);
    try {
      return await work();
    } catch (error) {
      this.fail();
      throw error;
    } finally {
      this.finishCurrentPhase();
    }
  }

  markReady(): void {
    this.finishCurrentPhase();
    this.totalMs = this.elapsedMs();
    this.state = "ready";
  }

  markFailed(): void {
    this.fail();
    this.finishCurrentPhase();
    this.totalMs = this.elapsedMs();
  }

  snapshot(): AgentBootSnapshot {
    const phasesMs = { ...this.phasesMs };
    if (this.currentPhase && this.currentPhaseStartedAt !== undefined) {
      phasesMs[this.currentPhase] = Math.max(
        0,
        Math.round(performance.now() - this.currentPhaseStartedAt),
      );
    }
    return {
      contractVersion: AGENT_BOOT_CONTRACT_VERSION,
      bootId: this.bootId,
      state: this.state,
      ...(this.currentPhase ? { currentPhase: this.currentPhase } : {}),
      ...(this.failedPhase ? { failedPhase: this.failedPhase } : {}),
      totalMs: this.totalMs ?? this.elapsedMs(),
      phasesMs,
    };
  }

  private elapsedMs(): number {
    return Math.max(0, Math.round(performance.now() - this.startedAt));
  }

  private start(phase: AgentBootPhase): void {
    this.finishCurrentPhase();
    this.currentPhase = phase;
    this.currentPhaseStartedAt = performance.now();
  }

  private fail(): void {
    this.state = "failed";
    if (this.currentPhase) this.failedPhase = this.currentPhase;
  }

  private finishCurrentPhase(): void {
    if (!this.currentPhase || this.currentPhaseStartedAt === undefined) return;
    this.phasesMs[this.currentPhase] = Math.max(
      0,
      Math.round(performance.now() - this.currentPhaseStartedAt),
    );
    this.currentPhase = undefined;
    this.currentPhaseStartedAt = undefined;
  }
}
