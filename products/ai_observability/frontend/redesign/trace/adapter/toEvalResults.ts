import { EvaluationRun } from '../../../evaluations/types'
import { EvalResult, EvalVerdict } from '../types'

function verdictOf(run: EvaluationRun): EvalVerdict {
    if (run.skipped || run.applicable === false || run.result === null) {
        return 'na'
    }
    return run.result ? 'pass' : 'fail'
}

export function toEvalResults(runs: EvaluationRun[]): EvalResult[] {
    return runs.map((run) => ({
        id: run.id,
        name: run.evaluation_name,
        verdict: verdictOf(run),
        reasoning: run.reasoning || null,
    }))
}
