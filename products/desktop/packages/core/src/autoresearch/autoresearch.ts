import { ROOT_LOGGER, type RootLogger } from "@posthog/di/logger";
import {
  type AgentSession,
  getBackoffDelay,
  getConfigOptionByCategory,
  type SagaLogger,
} from "@posthog/shared";
import { inject, injectable, preDestroy } from "inversify";
import { type SessionState, sessionStore } from "../sessions/sessionStore";
import {
  autoresearchStore,
  autoresearchStoreActions,
  getActiveRunForTask,
} from "./autoresearchStore";
import {
  AUTORESEARCH_GATE,
  AUTORESEARCH_SESSION_CLIENT,
  AUTORESEARCH_STORAGE_CLIENT,
  type AutoresearchGate,
  type AutoresearchSessionClient,
  type AutoresearchStorageClient,
  type StoredAutoresearchRun,
} from "./identifiers";
import {
  buildContinuationPrompt,
  buildImplementPrompt,
  buildKickoffPrompt,
  buildMeasurePrompt,
  buildPhasePrompt,
  buildReportReminderPrompt,
  buildResearchContinuationPrompt,
  buildResumePrompt,
  countPromptRequests,
  extractLastAgentTurnText,
  parseMetricReports,
  parseResearchReports,
  parseStreamedMetricReports,
} from "./prompts";
import {
  type AutoresearchConfigInput,
  type AutoresearchEndReason,
  type AutoresearchInterruptionReason,
  type AutoresearchReport,
  type AutoresearchRun,
  autoresearchConfigSchema,
  isTerminalRunStatus,
  parseStoredAutoresearchRun,
} from "./schemas";
import { computeBest, evaluateContinuation, isImprovement } from "./stats";

let runCounter = 0;

/**
 * A reportless turn only triggers its reaction (reminder, or the split-run
 * advance to the measure phase) after this grace period: `isPromptPending`
 * flips false before a failed/cancelled send's stop reason reaches us, and
 * the reaction must lose that race so a cancel/rate-limit pauses the run
 * before we re-prompt the agent the user just silenced.
 */
export const REMINDER_GRACE_MS = 1_500;
export const RECOVERY_BASE_DELAY_MS = 60_000;
export const RECOVERY_MAX_DELAY_MS = 15 * 60_000;
/** Recovery gives up after this many attempts; manual Resume still works. */
export const MAX_RECOVERY_ATTEMPTS = 20;

/**
 * Drives autoresearch runs: sends the kickoff prompt, watches the task's
 * agent session, and each time the agent finishes a turn parses the metric
 * report, records the iteration, and either continues the loop, reminds the
 * agent to report, or ends the run.
 *
 * Infrastructure obstacles (session drop, idle-kill, usage limit, app
 * restart) never end a run: they mark it `interrupted` and the service keeps
 * trying to bring it back by reconnecting the session when it can and
 * resuming the loop once the session is usable again. Only the user
 * (pause/stop), the iteration budget, the target, or a protocol breakdown
 * (the agent repeatedly not reporting) ends a run. Every mutation is
 * persisted through the storage client so runs survive app restarts.
 */
@injectable()
export class AutoresearchService {
  @inject(ROOT_LOGGER)
  private rootLogger!: RootLogger;

  @inject(AUTORESEARCH_SESSION_CLIENT)
  private sessionClient!: AutoresearchSessionClient;

  @inject(AUTORESEARCH_STORAGE_CLIENT)
  private storage!: AutoresearchStorageClient;

  @inject(AUTORESEARCH_GATE)
  private gate!: AutoresearchGate;

  private logScoped: SagaLogger | null = null;

  private get log(): SagaLogger {
    if (this.logScoped === null) {
      this.logScoped = this.rootLogger.scope("autoresearch");
    }
    return this.logScoped;
  }

  private unsubscribe: (() => void) | null = null;
  /** Reminders already sent for the in-flight iteration, per run id. */
  private remindersSent = new Map<string, number>();
  /**
   * Deferred reaction (reminder or measure-phase advance) to a reportless
   * turn, cancelled if an interruption/pause lands during the grace window.
   */
  private pendingReactions = new Map<string, ReturnType<typeof setTimeout>>();
  /**
   * Count of session/prompt requests already handled per run. A turn
   * completion is only processed when the count moved past this cursor.
   * `isPromptPending` flips without a new prompt when a send fails.
   */
  private promptCursor = new Map<string, number>();
  private streamedReportCursor = new Map<
    string,
    { promptCount: number; metricCount: number; researchCount: number }
  >();
  private recoveryTimers = new Map<string, ReturnType<typeof setTimeout>>();
  private recoveryAttempts = new Map<string, number>();
  /** Per-run write-through chain so persisted saves land in call order. */
  private persistChains = new Map<string, Promise<void>>();
  /**
   * Non-terminal run ids. The session subscription iterates only these, so a
   * long-lived app that has run autoresearch on many tasks does not pay
   * per-streamed-chunk work for runs that already ended.
   */
  private liveRunIds = new Set<string>();
  private hydratedTasks = new Set<string>();
  private rehydrated = false;

  /**
   * Register a run whose kickoff prompt the host has already delivered.
   * the create-task flow sends it as the new task's initial prompt. The
   * engine takes over from the agent's first reply.
   */
  registerRun(input: AutoresearchConfigInput): AutoresearchRun {
    const config = autoresearchConfigSchema.parse(input);

    const existing = getActiveRunForTask(
      autoresearchStore.getState(),
      config.taskId,
    );
    if (existing && !isTerminal(existing)) {
      throw new Error(
        `Autoresearch is already ${existing.status} for this task`,
      );
    }

    const session = getSessionForTask(sessionStore.getState(), config.taskId);
    const run: AutoresearchRun = {
      id: `ar-${Date.now()}-${++runCounter}`,
      config,
      status: "running",
      metricName: null,
      metricUnit: null,
      phase: null,
      originalModel: session ? currentSessionModel(session) : null,
      originalEffort: session ? currentSessionEffort(session) : null,
      researchFindings: [],
      iterations: [],
      startedAt: Date.now(),
      pausedAt: null,
      pausedDurationMs: 0,
      pauseIntervals: [],
      endedAt: null,
      endReason: null,
      interruptedReason: null,
      lastError: null,
    };

    autoresearchStoreActions.upsertRun(run);
    this.liveRunIds.add(run.id);
    const promptCount = session ? countPromptRequests(session.events) : 0;
    this.promptCursor.set(
      run.id,
      Math.max(0, promptCount - (session?.isPromptPending ? 1 : 0)),
    );
    this.persist(run.id);
    this.ensureSubscribed();
    this.log.info("Autoresearch run registered", {
      runId: run.id,
      taskId: config.taskId,
      direction: config.direction,
    });
    return run;
  }

  /**
   * Register a run and send its kickoff into the task's existing session.
   * Used to start a fresh run on a task that already ran autoresearch.
   * (For composer-created tasks the kickoff rides the initial prompt and the
   * baseline turn runs on the task's creation model. Stage models take over
   * from iteration 2.)
   */
  startRun(input: AutoresearchConfigInput): AutoresearchRun {
    const run = this.registerRun(input);
    // The kickoff's baseline is a measurement turn; apply the measure stage
    // (a no-op when nothing is configured).
    this.switchThenSend(
      run.id,
      run.config.taskId,
      measureStage(run),
      buildKickoffPrompt(run.config),
    );
    return run;
  }

  pauseRun(runId: string): void {
    const run = autoresearchStore.getState().runs[runId];
    if (!run || (run.status !== "running" && run.status !== "interrupted")) {
      return;
    }
    this.clearPendingReaction(runId);
    this.clearRecoveryTimer(runId);
    this.remindersSent.delete(runId);
    this.pauseClock(runId);
    autoresearchStoreActions.setRunStatus(runId, "paused");
    this.persist(runId);
    this.restoreOriginalStage(run);
    this.log.info("Autoresearch run paused", { runId });
  }

  resumeRun(runId: string): void {
    const run = autoresearchStore.getState().runs[runId];
    if (!run || (run.status !== "paused" && run.status !== "interrupted")) {
      return;
    }

    const decision = evaluateContinuation(run);
    if (decision.done) {
      this.endRun(runId, "completed", { endReason: decision.reason });
      return;
    }

    this.settlePausedClock(runId);
    this.clearRecoveryTimer(runId);
    const session = getSessionForTask(
      sessionStore.getState(),
      run.config.taskId,
    );
    if (
      session !== undefined &&
      session.status === "connected" &&
      (session.isPromptPending || session.isCompacting)
    ) {
      // A turn is already in flight; the loop re-engages when it completes.
      // Do not move the cursor. That prompt in progress is the next turn.
      autoresearchStoreActions.setRunStatus(runId, "running");
      this.persist(runId);
      this.log.info("Autoresearch run resumed", { runId });
      return;
    }
    if (!session || !isSessionUsable(session)) {
      // The session is down; let the recovery machinery bring it back and
      // resume the loop. Attempt immediately because the user asked for it now.
      // A manual resume is a fresh start, so it does not spend the automatic
      // recovery budget.
      this.recoveryAttempts.delete(runId);
      autoresearchStoreActions.setRunStatus(runId, "interrupted", {
        interruptedReason: run.interruptedReason ?? "session-error",
      });
      this.pauseClock(runId);
      this.persist(runId);
      void this.attemptRecovery(runId);
      return;
    }

    this.promptCursor.set(runId, countPromptRequests(session.events));
    autoresearchStoreActions.setRunStatus(runId, "running");
    this.persist(runId);
    this.log.info("Autoresearch run resumed", { runId });

    const current = autoresearchStore.getState().runs[runId];
    if (current) {
      this.switchThenSend(
        runId,
        run.config.taskId,
        phaseStage(current),
        buildPhasePrompt(current),
      );
    }
  }

  stopRun(runId: string): void {
    const run = autoresearchStore.getState().runs[runId];
    if (!run || isTerminal(run)) return;
    this.endRun(runId, "stopped", { endReason: "stopped-by-user" });
    this.log.info("Autoresearch run stopped", { runId });
  }

  /**
   * Restore persisted non-terminal runs after an app restart. Runs that were
   * mid-loop come back as `interrupted` and re-enter recovery, so a restart
   * pauses the loop instead of silently killing it.
   */
  async rehydrate(): Promise<void> {
    if (this.rehydrated) return;
    this.rehydrated = true;

    // Feature flagged: for ungated users the whole feature stays dormant.
    // no restored runs, no auto-resume, no session subscription.
    if (!(await this.gate.isEnabled())) {
      this.log.info("Autoresearch disabled by feature flag; skipping restore");
      return;
    }

    let stored: StoredAutoresearchRun[];
    try {
      stored = await this.storage.listOpen();
    } catch (error) {
      this.log.error("Failed to restore autoresearch runs", { error });
      return;
    }

    const runs = stored
      .map((row) => parseStoredAutoresearchRun(row.data))
      .filter((run): run is AutoresearchRun => run !== null);
    if (runs.length === 0) return;

    autoresearchStoreActions.hydrateRuns(runs);
    this.ensureSubscribed();

    const state = autoresearchStore.getState();
    for (const runId of Object.values(state.activeRunIdByTask)) {
      const run = state.runs[runId];
      if (!run || isTerminal(run)) continue;
      this.liveRunIds.add(run.id);
      if (run.status !== "interrupted") continue;
      // The stored blob still says "running"; persist the interruption.
      this.persist(run.id);
      this.scheduleRecovery(run.id);
    }
    this.log.info("Restored autoresearch runs", { count: runs.length });
  }

  /**
   * Load a task's persisted run history into the store (dashboard and
   * header entry point call this on mount). Cheap and idempotent.
   */
  async hydrateTask(taskId: string): Promise<void> {
    if (this.hydratedTasks.has(taskId)) return;
    this.hydratedTasks.add(taskId);

    let stored: StoredAutoresearchRun[];
    try {
      stored = await this.storage.listByTask(taskId);
    } catch (error) {
      this.hydratedTasks.delete(taskId);
      this.log.error("Failed to load autoresearch runs for task", {
        taskId,
        error,
      });
      return;
    }

    const runs = stored
      .map((row) => parseStoredAutoresearchRun(row.data))
      .filter((run): run is AutoresearchRun => run !== null);
    if (runs.length === 0) return;

    autoresearchStoreActions.hydrateRuns(runs);
    if (runs.some((run) => !isTerminal(run))) {
      this.ensureSubscribed();
      const active = getActiveRunForTask(autoresearchStore.getState(), taskId);
      if (active && !isTerminal(active)) {
        this.liveRunIds.add(active.id);
        if (active.status === "interrupted") this.scheduleRecovery(active.id);
      }
    }
  }

  @preDestroy()
  dispose(): void {
    this.unsubscribe?.();
    this.unsubscribe = null;
    for (const timer of this.pendingReactions.values()) clearTimeout(timer);
    this.pendingReactions.clear();
    for (const timer of this.recoveryTimers.values()) clearTimeout(timer);
    this.recoveryTimers.clear();
    this.remindersSent.clear();
    this.recoveryAttempts.clear();
    this.liveRunIds.clear();
  }

  private ensureSubscribed(): void {
    if (this.unsubscribe) return;
    this.unsubscribe = sessionStore.subscribe((state, prevState) => {
      this.onSessionStateChange(state, prevState);
    });
  }

  private onSessionStateChange(
    state: SessionState,
    prevState: SessionState,
  ): void {
    // Fires on every session-store mutation (per streamed chunk of every
    // session, app-wide); bail immediately when no run is live.
    if (this.liveRunIds.size === 0) return;

    const runs = autoresearchStore.getState().runs;
    for (const runId of this.liveRunIds) {
      const run = runs[runId];
      if (!run || isTerminal(run)) {
        this.liveRunIds.delete(runId);
        continue;
      }

      const session = getSessionForTask(state, run.config.taskId);
      if (!session) continue;
      const prevSession = getSessionForTask(prevState, run.config.taskId);

      if (session.status === "error" && prevSession?.status !== "error") {
        if (run.status === "running") {
          this.interrupt(
            run.id,
            "session-error",
            session.errorMessage ?? session.errorTitle ?? "Session error",
          );
        }
        continue;
      }

      if (run.status === "interrupted") {
        // Resume as soon as the session comes back. The reconnect may have
        // been ours (recovery) or the app's own reconciliation.
        if (isSessionUsable(session) && !isSessionUsable(prevSession)) {
          this.resumeFromInterruption(run.id);
        }
        continue;
      }

      const turnCompleted =
        prevSession?.isPromptPending === true &&
        session.isPromptPending === false;
      const promptCount = countPromptRequests(session.events);

      if (session.isPromptPending) {
        if (promptCount === 0) continue;
        this.ingestCompletedReports(run, session, false);
        continue;
      }
      if (promptCount <= (this.promptCursor.get(run.id) ?? 0)) continue;
      if (!turnCompleted) continue;

      const reports = this.ingestCompletedReports(run, session, true);
      this.promptCursor.set(run.id, promptCount);
      this.onAgentTurnComplete(run.id, reports);
    }
  }

  private ingestCompletedReports(
    run: AutoresearchRun,
    session: AgentSession,
    turnComplete: boolean,
  ): { hasMetric: boolean; hasResearch: boolean } {
    const text = extractLastAgentTurnText(session.events);
    const streamedMetricReports = parseStreamedMetricReports(text);
    const allMetricReports = turnComplete ? parseMetricReports(text) : [];
    const finalMetricReport =
      allMetricReports.length > streamedMetricReports.length
        ? allMetricReports.at(-1)
        : null;
    const metricReports = finalMetricReport
      ? [...streamedMetricReports, finalMetricReport]
      : streamedMetricReports;
    const researchReports = parseResearchReports(text);
    const promptCount = countPromptRequests(session.events);
    const existing = this.streamedReportCursor.get(run.id);
    const cursor =
      existing?.promptCount === promptCount
        ? existing
        : { promptCount, metricCount: 0, researchCount: 0 };

    if (metricReports.length === 0) {
      for (const report of researchReports.slice(cursor.researchCount)) {
        const current = autoresearchStore.getState().runs[run.id];
        if (!current || isTerminal(current)) break;
        if (current.iterations.length > 0) break;
        this.recordResearchFinding(current, report);
      }
    }
    for (const report of metricReports.slice(cursor.metricCount)) {
      const current = autoresearchStore.getState().runs[run.id];
      if (!current || isTerminal(current)) break;
      this.recordMetricReport(current, report);
    }
    this.streamedReportCursor.set(run.id, {
      promptCount,
      metricCount: metricReports.length,
      researchCount: researchReports.length,
    });
    return {
      hasMetric: metricReports.length > 0,
      hasResearch: metricReports.length === 0 && researchReports.length > 0,
    };
  }

  private recordResearchFinding(
    run: AutoresearchRun,
    researchReport: ReturnType<typeof parseResearchReports>[number],
  ): void {
    this.clearPendingReaction(run.id);
    this.remindersSent.delete(run.id);
    this.recoveryAttempts.delete(run.id);
    autoresearchStoreActions.appendResearchFinding(run.id, {
      index: run.researchFindings.length + 1,
      summary: researchReport.summary,
      finding: researchReport.finding,
      nextStep: researchReport.nextStep,
      area: researchReport.area,
      at: Date.now(),
    });
    this.persist(run.id);
  }

  private onAgentTurnComplete(
    runId: string,
    reports: { hasMetric: boolean; hasResearch: boolean },
  ): void {
    const run = autoresearchStore.getState().runs[runId];
    if (!run || run.status !== "running") return;
    if (reports.hasMetric) {
      const decision = evaluateContinuation(run);
      if (decision.done) {
        this.endRun(run.id, "completed", { endReason: decision.reason });
        this.log.info("Autoresearch run completed", {
          runId: run.id,
          reason: decision.reason,
          iterations: run.iterations.length,
        });
      } else {
        this.continueLoop(run);
      }
      return;
    }
    if (reports.hasResearch && run.iterations.length === 0) {
      void this.send(
        run.id,
        run.config.taskId,
        buildResearchContinuationPrompt(run),
      );
      return;
    }

    // Deferred: a reportless turn is either a split-run implement turn
    // (advance to measure) or a genuine missing report (remind). Both wait
    // out the grace window so a cancel/rate-limit resolving in the
    // meantime pauses/interrupts the run first.
    this.scheduleReportlessReaction(run.id);
  }

  private recordMetricReport(
    run: AutoresearchRun,
    report: AutoresearchReport,
  ): void {
    this.clearPendingReaction(run.id);
    this.remindersSent.delete(run.id);
    // The loop is demonstrably turning again; future interruptions restart
    // the recovery backoff from scratch.
    this.recoveryAttempts.delete(run.id);
    this.recordIteration(run, report);
    if (report.name || report.unit) {
      const current = autoresearchStore.getState().runs[run.id];
      // First named report wins; a stable label keeps the dashboard steady.
      if (current) {
        if (report.name && current.metricName === null) {
          autoresearchStoreActions.setMetricName(run.id, report.name);
        }
        if (report.unit && current.metricUnit === null) {
          autoresearchStoreActions.setMetricUnit(run.id, report.unit);
        }
      }
    }
    this.persist(run.id);
  }

  /** Kick off the next iteration after a recorded report. */
  private continueLoop(run: AutoresearchRun): void {
    if (!isSplitRun(run)) {
      this.switchThenSend(
        run.id,
        run.config.taskId,
        NO_STAGE,
        buildContinuationPrompt(run),
      );
      return;
    }
    autoresearchStoreActions.setPhase(run.id, "implement");
    this.persist(run.id);
    const current = autoresearchStore.getState().runs[run.id] ?? run;
    this.switchThenSend(
      run.id,
      run.config.taskId,
      implementStage(run),
      buildImplementPrompt(current),
    );
  }

  private beginMeasurePhase(run: AutoresearchRun): void {
    autoresearchStoreActions.setPhase(run.id, "measure");
    this.persist(run.id);
    const current = autoresearchStore.getState().runs[run.id] ?? run;
    this.switchThenSend(
      run.id,
      run.config.taskId,
      measureStage(run),
      buildMeasurePrompt(current),
    );
  }

  /**
   * Switch the session stage, including model or effort, then send in that
   * order, so the turn runs on the intended configuration rather than racing
   * the switch. A stage with nothing to set skips straight to the send with
   * no await, so ordering is unchanged for it. When there is a switch, a run
   * that ended, paused, or was interrupted during it does not send.
   */
  private switchThenSend(
    runId: string,
    taskId: string,
    stage: AutoresearchStage,
    prompt: string,
  ): void {
    if (stage.model === null && stage.effort === null) {
      void this.send(runId, taskId, prompt);
      return;
    }
    void this.switchStage(runId, taskId, stage).then(() => {
      const run = autoresearchStore.getState().runs[runId];
      if (!run || run.status !== "running") return;
      return this.send(runId, taskId, prompt);
    });
  }

  /**
   * Apply a stage model or effort to the session. Failures only warn. The
   * turn falls back to whatever the session currently has (effort options
   * can also legitimately differ per model, so a stale effort may be
   * rejected by the session).
   */
  private async switchStage(
    runId: string,
    taskId: string,
    stage: AutoresearchStage,
  ): Promise<void> {
    if (stage.model !== null) {
      try {
        await this.sessionClient.setModel(taskId, stage.model);
      } catch (error) {
        this.log.warn("Autoresearch model switch failed; continuing", {
          runId,
          model: stage.model,
          error,
        });
      }
    }
    if (stage.effort !== null) {
      try {
        await this.sessionClient.setEffort(taskId, stage.effort);
      } catch (error) {
        this.log.warn("Autoresearch effort switch failed; continuing", {
          runId,
          effort: stage.effort,
          error,
        });
      }
    }
  }

  /** Restore the session to the model/effort the user had before a split run. */
  private restoreOriginalStage(run: AutoresearchRun): void {
    if (!isSplitRun(run)) return;
    void this.switchStage(run.id, run.config.taskId, {
      model: run.originalModel ?? run.config.implementModel,
      effort: run.originalEffort ?? run.config.implementEffort,
    });
  }

  /**
   * React to a reportless turn once the grace window has passed and no
   * cancel/rate-limit/interruption intervened. In a split run's implement
   * phase that means advancing to the measure phase; otherwise it is a
   * missing report. Remind once, then fail.
   */
  private scheduleReportlessReaction(runId: string): void {
    const run = autoresearchStore.getState().runs[runId];
    if (!run || run.status !== "running") return;
    if (this.pendingReactions.has(runId)) return;

    const timer = setTimeout(() => {
      this.pendingReactions.delete(runId);
      const current = autoresearchStore.getState().runs[runId];
      if (!current || current.status !== "running") return;

      if (isSplitRun(current) && current.phase === "implement") {
        this.beginMeasurePhase(current);
        return;
      }

      const reminders = this.remindersSent.get(runId) ?? 0;
      if (reminders >= 1) {
        this.endRun(runId, "failed", {
          endReason: "missing-report",
          lastError: "The agent stopped reporting the metric after a reminder.",
        });
        return;
      }
      this.remindersSent.set(runId, reminders + 1);
      this.log.warn("Autoresearch turn had no metric report, reminding", {
        runId,
      });
      void this.send(
        runId,
        current.config.taskId,
        buildReportReminderPrompt(current),
      );
    }, REMINDER_GRACE_MS);
    this.pendingReactions.set(runId, timer);
  }

  private recordIteration(
    run: AutoresearchRun,
    report: AutoresearchReport,
  ): void {
    const previous = run.iterations[run.iterations.length - 1] ?? null;
    const best = computeBest(run.iterations, run.config.direction);
    const bestValue = isImprovement(
      report.value,
      best?.value ?? null,
      run.config.direction,
    )
      ? report.value
      : (best?.value ?? report.value);

    autoresearchStoreActions.appendIteration(run.id, {
      index: run.iterations.length + 1,
      value: report.value,
      bestValue,
      delta: previous ? report.value - previous.value : null,
      summary: report.summary,
      hypothesis: report.hypothesis,
      plan: report.plan,
      approach: report.approach,
      at: Date.now(),
    });
  }

  private async send(
    runId: string,
    taskId: string,
    prompt: string,
  ): Promise<void> {
    try {
      const { stopReason } = await this.sessionClient.sendPrompt(
        taskId,
        prompt,
      );
      if (stopReason === "rate_limited") {
        this.interrupt(
          runId,
          "rate-limited",
          "Usage limit reached. The loop retries automatically.",
        );
      } else if (stopReason === "cancelled") {
        // The user stopped the turn. Hand them control instead of
        // immediately re-prompting the agent they just silenced.
        const run = autoresearchStore.getState().runs[runId];
        if (run?.status === "running") {
          this.clearPendingReaction(runId);
          this.remindersSent.delete(runId);
          this.pauseClock(runId);
          autoresearchStoreActions.setRunStatus(runId, "paused");
          this.persist(runId);
          this.restoreOriginalStage(run);
          this.log.info("Autoresearch paused after user cancelled the turn", {
            runId,
          });
        }
      } else if (stopReason === "queued") {
        // The session was busy (a turn/compaction in flight), so our prompt
        // sits in the session queue and drains when it frees up, producing
        // a turn the subscription processes normally. Nothing to do but note
        // it; if the session never frees, its error path drives recovery.
        this.log.warn("Autoresearch prompt queued behind a busy session", {
          runId,
        });
      }
    } catch (error) {
      this.log.error("Failed to send autoresearch prompt", { runId, error });
      const current = autoresearchStore.getState().runs[runId];
      if (!current || isTerminal(current)) return;
      this.interrupt(
        runId,
        "send-failed",
        error instanceof Error ? error.message : String(error),
      );
    }
  }

  private interrupt(
    runId: string,
    reason: AutoresearchInterruptionReason,
    lastError?: string,
  ): void {
    const run = autoresearchStore.getState().runs[runId];
    if (!run || isTerminal(run)) return;
    // A user pause outranks automation: record nothing, resume nothing.
    if (run.status === "paused") return;

    this.clearPendingReaction(runId);
    // A fresh interruption gets its own reminder budget on resume.
    this.remindersSent.delete(runId);
    this.pauseClock(runId);
    autoresearchStoreActions.setRunStatus(runId, "interrupted", {
      interruptedReason: reason,
      lastError,
    });
    this.persist(runId);
    this.log.warn("Autoresearch run interrupted", { runId, reason, lastError });
    this.scheduleRecovery(runId);
  }

  private scheduleRecovery(runId: string): void {
    if (this.recoveryTimers.has(runId)) return;
    const attempts = this.recoveryAttempts.get(runId) ?? 0;
    if (attempts >= MAX_RECOVERY_ATTEMPTS) {
      this.log.warn("Autoresearch recovery gave up; resume manually", {
        runId,
        attempts,
      });
      return;
    }
    const delay = getBackoffDelay(attempts, {
      initialDelayMs: RECOVERY_BASE_DELAY_MS,
      maxDelayMs: RECOVERY_MAX_DELAY_MS,
    });
    const timer = setTimeout(() => {
      this.recoveryTimers.delete(runId);
      void this.attemptRecovery(runId);
    }, delay);
    this.recoveryTimers.set(runId, timer);
  }

  private async attemptRecovery(runId: string): Promise<void> {
    const run = autoresearchStore.getState().runs[runId];
    if (!run || run.status !== "interrupted") return;
    this.recoveryAttempts.set(
      runId,
      (this.recoveryAttempts.get(runId) ?? 0) + 1,
    );

    const session = getSessionForTask(
      sessionStore.getState(),
      run.config.taskId,
    );
    if (isSessionUsable(session)) {
      this.resumeFromInterruption(runId);
      return;
    }

    if (
      !session ||
      session.status === "error" ||
      session.status === "disconnected"
    ) {
      try {
        await this.sessionClient.reconnect(run.config.taskId);
      } catch (error) {
        this.log.warn("Autoresearch session reconnect failed; will retry", {
          runId,
          error,
        });
      }
    }

    // Either the connected transition resumes the run, or the next tick does.
    if (autoresearchStore.getState().runs[runId]?.status === "interrupted") {
      this.scheduleRecovery(runId);
    }
  }

  private resumeFromInterruption(runId: string): void {
    const run = autoresearchStore.getState().runs[runId];
    if (!run || run.status !== "interrupted") return;
    const reason = run.interruptedReason ?? "session-error";

    const decision = evaluateContinuation(run);
    if (decision.done) {
      this.endRun(runId, "completed", { endReason: decision.reason });
      return;
    }

    this.settlePausedClock(runId);
    this.clearRecoveryTimer(runId);
    const session = getSessionForTask(
      sessionStore.getState(),
      run.config.taskId,
    );
    this.promptCursor.set(
      runId,
      session ? countPromptRequests(session.events) : 0,
    );
    autoresearchStoreActions.setRunStatus(runId, "running");
    this.persist(runId);
    this.log.info("Autoresearch run resuming after interruption", {
      runId,
      reason,
    });
    // A reconnected session comes back on its default model; switchThenSend
    // re-applies the phase's stage before re-entering the loop.
    this.switchThenSend(
      runId,
      run.config.taskId,
      phaseStage(run),
      buildResumePrompt(run, reason),
    );
  }

  private endRun(
    runId: string,
    status: "completed" | "stopped" | "failed",
    options: { endReason: AutoresearchEndReason; lastError?: string },
  ): void {
    this.settlePausedClock(runId);
    const run = autoresearchStore.getState().runs[runId];
    autoresearchStoreActions.setRunStatus(runId, status, options);
    this.persist(runId);
    this.clearPendingReaction(runId);
    this.clearRecoveryTimer(runId);
    this.remindersSent.delete(runId);
    this.recoveryAttempts.delete(runId);
    this.promptCursor.delete(runId);
    this.streamedReportCursor.delete(runId);
    this.liveRunIds.delete(runId);
    if (run) this.restoreOriginalStage(run);
  }

  private pauseClock(runId: string): void {
    const run = autoresearchStore.getState().runs[runId];
    if (!run || run.pausedAt != null) return;
    autoresearchStoreActions.setPauseTiming(
      runId,
      Date.now(),
      run.pausedDurationMs ?? 0,
      run.pauseIntervals ?? [],
    );
  }

  private settlePausedClock(runId: string): void {
    const run = autoresearchStore.getState().runs[runId];
    if (!run || run.pausedAt == null) return;
    const endedAt = Date.now();
    autoresearchStoreActions.setPauseTiming(
      runId,
      null,
      (run.pausedDurationMs ?? 0) + Math.max(0, endedAt - run.pausedAt),
      [...(run.pauseIntervals ?? []), { startedAt: run.pausedAt, endedAt }],
    );
  }

  private clearPendingReaction(runId: string): void {
    const timer = this.pendingReactions.get(runId);
    if (timer) clearTimeout(timer);
    this.pendingReactions.delete(runId);
  }

  private clearRecoveryTimer(runId: string): void {
    const timer = this.recoveryTimers.get(runId);
    if (timer) clearTimeout(timer);
    this.recoveryTimers.delete(runId);
  }

  /**
   * Write-through persistence. Saves for a run are chained so they land in
   * call order. A later transition can never be overwritten by a pending
   * earlier one. The in-memory store stays authoritative.
   */
  private persist(runId: string): void {
    const run = autoresearchStore.getState().runs[runId];
    if (!run) return;
    const record: StoredAutoresearchRun = {
      id: run.id,
      taskId: run.config.taskId,
      endedAt: run.endedAt ? new Date(run.endedAt).toISOString() : null,
      data: JSON.stringify(run),
    };
    const previous = this.persistChains.get(runId) ?? Promise.resolve();
    const next = previous
      .catch(() => {})
      .then(() => this.storage.save(record))
      .catch((error) => {
        this.log.error("Failed to persist autoresearch run", { runId, error });
      });
    this.persistChains.set(runId, next);
  }
}

function isTerminal(run: AutoresearchRun): boolean {
  return isTerminalRunStatus(run.status);
}

/** A session configuration a stage runs on; null fields are left alone. */
interface AutoresearchStage {
  model: string | null;
  effort: string | null;
}

const NO_STAGE: AutoresearchStage = { model: null, effort: null };

function implementStage(run: AutoresearchRun): AutoresearchStage {
  return {
    model: run.config.implementModel,
    effort: run.config.implementEffort,
  };
}

function measureStage(run: AutoresearchRun): AutoresearchStage {
  return { model: run.config.measureModel, effort: run.config.measureEffort };
}

/**
 * Split runs alternate an implement turn and a measure turn per iteration.
 * Any difference between the stages, model or effort, makes the run split;
 * identical stages run as single turns with no mid-loop switching.
 */
function isSplitRun(run: AutoresearchRun): boolean {
  return (
    run.config.implementModel !== run.config.measureModel ||
    run.config.implementEffort !== run.config.measureEffort
  );
}

/**
 * The stage for the run's current phase. A null phase is the baseline
 * measurement when nothing is recorded yet, otherwise it re-enters at the
 * implement half.
 */
function phaseStage(run: AutoresearchRun): AutoresearchStage {
  if (!isSplitRun(run)) return NO_STAGE;
  if (run.phase === "measure") return measureStage(run);
  if (run.phase === "implement") return implementStage(run);
  return run.iterations.length === 0 ? measureStage(run) : implementStage(run);
}

function isSessionUsable(session: AgentSession | undefined): boolean {
  return (
    session !== undefined &&
    session.status === "connected" &&
    !session.isPromptPending &&
    !session.isCompacting
  );
}

/** The session's currently-selected model, or null if none is set. */
function currentSessionModel(session: AgentSession): string | null {
  const option = getConfigOptionByCategory(session.configOptions, "model");
  return option?.type === "select" ? (option.currentValue ?? null) : null;
}

/** The session's currently-selected reasoning effort, or null if none. */
function currentSessionEffort(session: AgentSession): string | null {
  const option = getConfigOptionByCategory(
    session.configOptions,
    "thought_level",
  );
  return option?.type === "select" ? (option.currentValue ?? null) : null;
}

function getSessionForTask(
  state: SessionState,
  taskId: string,
): AgentSession | undefined {
  const taskRunId = state.taskIdIndex[taskId];
  return taskRunId ? state.sessions[taskRunId] : undefined;
}
