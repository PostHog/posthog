import { EvaluationJudgeModelPicker } from '../components/EvaluationJudgeModelPicker'

/** The model a judge or decision model runs on, from the team's AI providers. */
export function EvaluationModelPanel(): JSX.Element {
    return (
        <div className="w-80 max-w-full">
            <EvaluationJudgeModelPicker />
        </div>
    )
}
