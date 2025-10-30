import { BindLogic, useValues } from 'kea'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { useFileSystemLogView } from 'lib/hooks/useFileSystemLogView'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import type { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'

import { ExperimentForm } from './ExperimentForm'
import { ExperimentView } from './ExperimentView/ExperimentView'
import { CreateExperiment } from './create/CreateExperiment'
import { type ExperimentLogicProps, FORM_MODES, experimentLogic } from './experimentLogic'
import { type ExperimentSceneLogicProps, experimentSceneLogic } from './experimentSceneLogic'

export const scene: SceneExport<ExperimentSceneLogicProps> = {
    component: Experiment,
    logic: experimentSceneLogic,
    paramsToProps: ({ params: { id, formMode } }) => ({
        experimentId: id === 'new' ? 'new' : parseInt(id, 10),
        formMode: formMode || (id === 'new' ? FORM_MODES.create : FORM_MODES.update),
        // tabId is automatically added by sceneLogic
    }),
}

export function Experiment({ tabId }: ExperimentSceneLogicProps): JSX.Element {
    if (!tabId) {
        throw new Error('<Experiment /> must receive a tabId prop')
    }
    const { formMode, experimentMissing, experimentId } = useValues(experimentSceneLogic({ tabId }))
    const { currentTeamId } = useValues(teamLogic)
    const isCreateFormEnabled = useFeatureFlag('EXPERIMENTS_CREATE_FORM', 'test')

    useFileSystemLogView({
        type: 'experiment',
        ref: experimentId,
        enabled: Boolean(currentTeamId && !experimentMissing && typeof experimentId === 'number'),
        deps: [currentTeamId, experimentId, experimentMissing],
    })

    const logicProps: ExperimentLogicProps = { experimentId, formMode, tabId }
    useAttachedLogic(experimentLogic(logicProps), experimentSceneLogic({ tabId }))

    if (experimentMissing) {
        return <NotFound object="experiment" />
    }

    if (isCreateFormEnabled && formMode === FORM_MODES.create) {
        return (
            <BindLogic logic={experimentLogic} props={logicProps}>
                <CreateExperiment />
            </BindLogic>
        )
    }

    return (
        <BindLogic logic={experimentLogic} props={logicProps}>
            {formMode && ([FORM_MODES.create, FORM_MODES.duplicate] as string[]).includes(formMode) ? (
                <ExperimentForm />
            ) : (
                <ExperimentView />
            )}
        </BindLogic>
    )
}
