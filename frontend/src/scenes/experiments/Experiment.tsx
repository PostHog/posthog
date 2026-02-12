import { BindLogic, useValues } from 'kea'

import { NotFound } from 'lib/components/NotFound'
import { useFileSystemLogView } from 'lib/hooks/useFileSystemLogView'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import type { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { ExperimentForm } from './ExperimentForm'
import { createExperimentLogic } from './ExperimentForm/createExperimentLogic'
import { ExperimentView } from './ExperimentView/ExperimentView'
import { ExperimentWizard } from './ExperimentWizard/ExperimentWizard'
import { experimentWizardLogic } from './ExperimentWizard/experimentWizardLogic'
import { type ExperimentLogicProps, FORM_MODES, experimentLogic } from './experimentLogic'
import { type ExperimentSceneLogicProps, experimentSceneLogic } from './experimentSceneLogic'

export const scene: SceneExport<ExperimentSceneLogicProps> = {
    component: Experiment,
    logic: experimentSceneLogic,
    productKey: ProductKey.EXPERIMENTS,
    paramsToProps: ({ params: { id, formMode } }) => ({
        experimentId: id === 'new' ? 'new' : parseInt(id, 10),
        formMode: formMode || (id === 'new' ? FORM_MODES.create : FORM_MODES.update),
        // tabId is automatically added by sceneLogic
    }),
}

export function Experiment(props: ExperimentSceneLogicProps): JSX.Element {
    const { tabId } = props

    if (!tabId) {
        throw new Error('<Experiment /> must receive a tabId prop')
    }
    const { formMode, experimentMissing, experimentId, wizardMode } = useValues(experimentSceneLogic({ tabId }))
    const { currentTeamId } = useValues(teamLogic)

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

    const isCreateMode = formMode && ([FORM_MODES.create, FORM_MODES.duplicate] as string[]).includes(formMode)

    return (
        <BindLogic logic={experimentLogic} props={logicProps}>
            {isCreateMode ? (
                <ExperimentCreateMode tabId={tabId} wizardMode={wizardMode} />
            ) : (
                <ExperimentView tabId={tabId} />
            )}
        </BindLogic>
    )
}

function ExperimentCreateMode({ tabId, wizardMode }: { tabId: string; wizardMode: boolean }): JSX.Element {
    // Mount createExperimentLogic at this level so it persists across wizard <-> form switches
    const logic = createExperimentLogic({ tabId })
    useAttachedLogic(logic, experimentSceneLogic({ tabId }))

    if (wizardMode) {
        return (
            <BindLogic logic={experimentWizardLogic} props={{ tabId }}>
                <ExperimentWizard />
            </BindLogic>
        )
    }

    return <ExperimentForm tabId={tabId} />
}
