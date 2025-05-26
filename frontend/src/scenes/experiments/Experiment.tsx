import { useValues } from 'kea'
import { NotFound } from 'lib/components/NotFound'
import { SceneExport } from 'scenes/sceneTypes'

import { ExperimentForm } from './ExperimentForm'
import { experimentLogic, ExperimentLogicProps } from './experimentLogic'
import { ExperimentView } from './ExperimentView/ExperimentView'

export const scene: SceneExport = {
    component: Experiment,
    logic: experimentLogic,
    paramsToProps: ({ params: { id, action } }): ExperimentLogicProps => ({
        experimentId: id === 'new' ? 'new' : parseInt(id),
        action: action || (id === 'new' ? 'create' : 'update'),
    }),
}

export function Experiment(): JSX.Element {
    const { action, experimentMissing } = useValues(experimentLogic)

    if (experimentMissing) {
        return <NotFound object="experiment" />
    }

    return ['create', 'update'].includes(action) ? <ExperimentForm /> : <ExperimentView />
}
