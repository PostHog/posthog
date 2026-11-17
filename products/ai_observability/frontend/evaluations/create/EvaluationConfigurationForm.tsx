import { BindLogic, useMountedLogic } from 'kea'

import { evaluationVolumeLogic } from '../evaluationVolumeLogic'
import { llmEvaluationLogic } from '../llmEvaluationLogic'
import { EvaluationFormSteps } from './EvaluationFormSteps'

/** A saved evaluation's settings, in the same steps as the new evaluation page. The page header saves them. */
export function EvaluationConfigurationForm(): JSX.Element {
    const { props } = useMountedLogic(llmEvaluationLogic)

    return (
        <BindLogic logic={evaluationVolumeLogic} props={props}>
            <EvaluationFormSteps checklist={[]} />
        </BindLogic>
    )
}
