import { useValues } from 'kea'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import type { SceneExport } from 'scenes/sceneTypes'

import { ExperimentForm } from './ExperimentForm'
import { ExperimentView } from './ExperimentView/ExperimentView'
import { CreateExperiment } from './create/CreateExperiment'
import { type ExperimentLogicProps, FORM_MODES, experimentLogic } from './experimentLogic'

export const scene: SceneExport<ExperimentLogicProps> = {
    component: Experiment,
    logic: experimentLogic,
    paramsToProps: ({ params: { id, formMode } }) => ({
        experimentId: id === 'new' ? 'new' : parseInt(id, 10),
        formMode: formMode || (id === 'new' ? FORM_MODES.create : FORM_MODES.update),
    }),
}

export function Experiment(): JSX.Element {
    const { formMode, experimentMissing } = useValues(experimentLogic)
    const isUnifiedCreateFormEnabled = useFeatureFlag('EXPERIMENTS_UNIFIED_CREATE_FORM', 'test')

    if (experimentMissing) {
        return <NotFound object="experiment" />
    }

    if (isUnifiedCreateFormEnabled && formMode === FORM_MODES.create) {
        return <CreateExperiment />
    }

    return ([FORM_MODES.create, FORM_MODES.duplicate] as string[]).includes(formMode) ? (
        <ExperimentForm />
    ) : (
        <ExperimentView />
    )
}
