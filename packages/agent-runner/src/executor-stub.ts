import { ExecutorTurnOutput, SessionExecutor } from './executor'

/**
 * Placeholder until the Claude Agent SDK integration lands. Defined here (not in tests)
 * so a stripped-down runner process can still boot end-to-end before the real executor
 * is wired in. Treats every turn as "complete with an empty output."
 */
export class NotImplementedExecutor implements SessionExecutor {
    async runTurn(): Promise<ExecutorTurnOutput> {
        return {
            kind: 'failed',
            error: 'Claude Agent SDK executor is not implemented yet. Wire one up in src/index.ts.',
        }
    }
}
