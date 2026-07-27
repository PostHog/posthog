import { BindLogic, useMountedLogic, useValues } from 'kea'

import { NotFound } from 'lib/components/NotFound'
import { useFileSystemLogView } from 'lib/hooks/useFileSystemLogView'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import type { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { createExperimentLogic } from './ExperimentForm/createExperimentLogic'
import { type ExperimentLogicProps, FORM_MODES, experimentLogic } from './experimentLogic'
import { experimentSceneLogic } from './experimentSceneLogic'
import { ExperimentView } from './ExperimentView/ExperimentView'
import { ExperimentWizard } from './ExperimentWizard/ExperimentWizard'
import { experimentWizardLogic } from './ExperimentWizard/experimentWizardLogic'

export const scene: SceneExport = {
    component: Experiment,
    logic: experimentSceneLogic,
    productKey: ProductKey.EXPERIMENTS,
    paramsToProps: ({ params: { id, formMode } }) => ({
        experimentId: id === 'new' ? 'new' : parseInt(id, 10),
        formMode: formMode || (id === 'new' ? FORM_MODES.create : FORM_MODES.update),
    }),
}

export function Experiment(): JSX.Element {
    const { formMode, experimentMissing, experimentId } = useValues(experimentSceneLogic)
    const { currentTeamId } = useValues(teamLogic)

    useFileSystemLogView({
        type: 'experiment',
        ref: experimentId,
        enabled: Boolean(currentTeamId && !experimentMissing && typeof experimentId === 'number'),
    })

    const logicProps: ExperimentLogicProps = { experimentId, formMode }
    useAttachedLogic(experimentLogic(logicProps), experimentSceneLogic)

    if (experimentMissing) {
        return <NotFound object="experiment" />
    }

    const isCreateMode = formMode && ([FORM_MODES.create, FORM_MODES.duplicate] as string[]).includes(formMode)

    return (
        <BindLogic logic={experimentLogic} props={logicProps}>
            {isCreateMode ? <ExperimentCreateMode /> : <ExperimentView />}
        </BindLogic>
    )
}

function ExperimentCreateMode(): JSX.Element {
    const logic = createExperimentLogic()
    useMountedLogic(logic)

    return (
        <BindLogic logic={experimentWizardLogic} props={{}}>
            <ExperimentWizard />
        </BindLogic>
    )
}
