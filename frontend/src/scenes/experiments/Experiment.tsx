import './Experiment.scss'

import { useValues } from 'kea'
import { NotFound } from 'lib/components/NotFound'
import { SceneExport } from 'scenes/sceneTypes'

import { ExperimentForm } from './ExperimentForm'
import { experimentLogic, ExperimentLogicProps } from './experimentLogic'
import { ExperimentView } from './ExperimentView/ExperimentView'

export const scene: SceneExport = {
    component: Experiment,
    logic: experimentLogic,
    paramsToProps: ({ params: { id } }): ExperimentLogicProps => ({
        experimentId: id === 'new' ? 'new' : parseInt(id),
    }),
}

export function Experiment(): JSX.Element {
    const { experimentId, editingExistingExperiment, experimentMissing } = useValues(experimentLogic)

    if (experimentMissing) {
        return <NotFound object="experiment" />
    }

    return experimentId === 'new' || editingExistingExperiment ? <ExperimentForm /> : <ExperimentView />
}
