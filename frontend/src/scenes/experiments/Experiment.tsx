import { useValues } from 'kea'
import { NotFound } from 'lib/components/NotFound'
import { SceneExport } from 'scenes/sceneTypes'

import { ExperimentForm } from './ExperimentForm'
import { experimentLogic, ExperimentLogicProps, FORM_MODES } from './experimentLogic'
import { ExperimentView } from './ExperimentView/ExperimentView'

export const scene: SceneExport = {
    component: Experiment,
    logic: experimentLogic,
    paramsToProps: ({ params: { id, formMode } }): ExperimentLogicProps => ({
        experimentId: id === 'new' ? 'new' : parseInt(id, 10),
        formMode: formMode || (id === 'new' ? FORM_MODES.create : FORM_MODES.update),
    }),
}

export function Experiment(): JSX.Element {
    const { formMode, experimentMissing } = useValues(experimentLogic)

    if (experimentMissing) {
        return <NotFound object="experiment" />
    }

    return ([FORM_MODES.create, FORM_MODES.duplicate] as string[]).includes(formMode) ? (
        <ExperimentForm />
    ) : (
        <ExperimentView />
    )
}
