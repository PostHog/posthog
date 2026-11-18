/**
 * Configuration for a single saga step
 */
export interface SagaStep<T> {
  /** Unique name for this step (used in logging) */
  name: string;
  /** The forward action to execute */
  execute: () => Promise<T>;
  /** The rollback action to undo this step (receives the execute result) */
  rollback: (result: T) => Promise<void>;
}

/**
 * Result of a saga execution
 */
export type SagaResult<T, TFailedStep extends string = string> =
  | { success: true; data: T }
  | { success: false; error: string; failedStep: TFailedStep };

export interface SagaLogger {
  info(message: string, data?: Record<string, unknown>): void;
  debug(message: string, data?: Record<string, unknown>): void;
  error(message: string, data?: Record<string, unknown>): void;
  warn(message: string, data?: Record<string, unknown>): void;
}

const consoleLogger: SagaLogger = {
  info: (_message, _data) => {},
  debug: (_message, _data) => {},
  error: (_message, _data) => {},
  warn: (_message, _data) => {},
};

/**
 * Abstract base class for implementing our Saga pattern.
 *
 * Subclasses implement the `execute` method, using `this.step()` to define
 * each step with its compensating action. If any step throws, all completed
 * steps are automatically rolled back in reverse order.
 *
 * The failed step name is automatically tracked from the step's `name` property.
 *
 * @template TInput - The input type for the saga
 * @template TOutput - The successful output type
 */
export abstract class Saga<TInput, TOutput> {
  abstract readonly sagaName: string;

  private completedSteps: Array<{
    name: string;
    rollback: () => Promise<void>;
  }> = [];
  private currentStepName = "unknown";
  private stepTimings: Array<{ name: string; durationMs: number }> = [];
  protected readonly log: SagaLogger;

  constructor(logger?: SagaLogger) {
    this.log = logger ?? consoleLogger;
  }

  /**
   * Run the saga with the given input.
   * Returns a discriminated union result - either success with data or failure with error details.
   */
  async run(input: TInput): Promise<SagaResult<TOutput>> {
    this.completedSteps = [];
    this.currentStepName = "unknown";
    this.stepTimings = [];

    const sagaStart = performance.now();

    try {
      const result = await this.execute(input);

      const totalDuration = performance.now() - sagaStart;
      this.log.debug("Saga completed successfully", {
        sagaName: this.sagaName,
        stepsCompleted: this.completedSteps.length,
        totalDurationMs: Math.round(totalDuration),
        stepTimings: this.stepTimings,
      });

      return { success: true, data: result };
    } catch (error) {
      this.log.error("Saga failed, initiating rollback", {
        sagaName: this.sagaName,
        failedStep: this.currentStepName,
        error: error instanceof Error ? error.message : String(error),
        completedStepTimings: this.stepTimings,
      });

      await this.rollback();

      return {
        success: false,
        error: error instanceof Error ? error.message : String(error),
        failedStep: this.currentStepName,
      };
    }
  }

  /**
   * Implement this method to define the saga's steps.
   * Use `this.step()` to execute each step with its compensating action.
   */
  protected abstract execute(input: TInput): Promise<TOutput>;

  /**
   * Execute a step with its rollback action.
   * If the step succeeds, its rollback action is stored for potential rollback.
   * The step name is automatically tracked for error reporting.
   *
   * @param config - Step configuration with name, execute, and rollback functions
   * @returns The result of the execute function
   * @throws Re-throws any error from the execute function (triggers rollback)
   */
  protected async step<T>(config: SagaStep<T>): Promise<T> {
    this.currentStepName = config.name;

    const stepStart = performance.now();
    const result = await config.execute();
    const durationMs = Math.round(performance.now() - stepStart);

    this.stepTimings.push({ name: config.name, durationMs });

    this.completedSteps.push({
      name: config.name,
      rollback: () => config.rollback(result),
    });

    return result;
  }

  /**
   * Execute a step that doesn't need rollback.
   * Useful for read-only operations or operations that are idempotent.
   * The step name is automatically tracked for error reporting.
   *
   * @param name - Step name for logging and error tracking
   * @param execute - The action to execute
   * @returns The result of the execute function
   */
  protected async readOnlyStep<T>(
    name: string,
    execute: () => Promise<T>,
  ): Promise<T> {
    this.currentStepName = name;

    const stepStart = performance.now();
    const result = await execute();
    const durationMs = Math.round(performance.now() - stepStart);

    this.stepTimings.push({ name, durationMs });
    return result;
  }

  /**
   * Roll back all completed steps in reverse order.
   * Rollback errors are logged but don't stop the rollback of other steps.
   */
  private async rollback(): Promise<void> {
    this.log.info("Rolling back saga", {
      stepsToRollback: this.completedSteps.length,
    });

    const stepsReversed = [...this.completedSteps].reverse();

    for (const step of stepsReversed) {
      try {
        await step.rollback();
      } catch (error) {
        // Log but continue - we want to attempt all rollbacks
        this.log.error(`Failed to rollback step: ${step.name}`, {
          error: error instanceof Error ? error.message : String(error),
        });
      }
    }

    this.log.info("Rollback completed", {
      stepsAttempted: this.completedSteps.length,
    });
  }

  /**
   * Get the number of completed steps (useful for testing)
   */
  protected getCompletedStepCount(): number {
    return this.completedSteps.length;
  }
}
