import { useValues } from 'kea'

import { NotFound } from 'lib/components/NotFound'
import { SceneExport } from 'scenes/sceneTypes'

import { ExperimentForm } from './ExperimentForm'
import { ExperimentView } from './ExperimentView/ExperimentView'
import { ExperimentLogicProps, FORM_MODES, experimentLogic } from './experimentLogic'
import { ExperimentView as LegacyExperimentView } from './legacy/ExperimentView'
import { isLegacyExperiment } from './utils'

export const scene: SceneExport<ExperimentLogicProps> = {
    component: Experiment,
    logic: experimentLogic,
    paramsToProps: ({ params: { id, formMode } }) => ({
        experimentId: id === 'new' ? 'new' : parseInt(id, 10),
        formMode: formMode || (id === 'new' ? FORM_MODES.create : FORM_MODES.update),
    }),
}

export function Experiment(): JSX.Element {
    const { formMode, experimentMissing, experiment } = useValues(experimentLogic)

    if (experimentMissing) {
        return <NotFound object="experiment" />
    }

    return ([FORM_MODES.create, FORM_MODES.duplicate] as string[]).includes(formMode) ? (
        <ExperimentForm />
    ) : isLegacyExperiment(experiment) ? (
        <LegacyExperimentView experiment={experiment} />
    ) : (
        <ExperimentView />
    )
}
