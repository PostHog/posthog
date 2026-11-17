import { useActions, useValues } from 'kea'

import { IconPause, IconPlay, IconRefresh } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import { autoresearchPipelineLogic } from './autoresearchPipelineLogic'
import { AutoresearchModelRoleEnumApi } from './generated/api.schemas'
import { QuillPipelineActions } from './pipeline/QuillPipelineActions'
import { QuillScoreNowButton } from './pipeline/QuillScoreNowButton'

const RESOURCE_TYPE = 'autoresearch-model'

export function AutoresearchPipelineSceneMenuBar(): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <AutoresearchPipelineSceneMenuBarInner /> : null
}

function AutoresearchPipelineSceneMenuBarInner(): JSX.Element {
    const { pipeline, pipelineLoading, models, scoreResultLoading, activeScoreRun } =
        useValues(autoresearchPipelineLogic)
    const { scoreNow, pausePipeline, resumePipeline } = useActions(autoresearchPipelineLogic)
    const hasChampion = models.some((m) => m.role === AutoresearchModelRoleEnumApi.Champion)
    const paused = pipeline?.status === 'paused'
    const running = pipeline?.status === 'running'

    const actions: SceneAction[] = [
        ...(pipeline && pipeline.status !== 'archived'
            ? ([
                  {
                      group: 'edit',
                      section: 'run',
                      id: `${RESOURCE_TYPE}-menubar-score`,
                      label: 'Score now',
                      icon: <IconRefresh />,
                      disabledReason: paused
                          ? 'Resume the model to score it'
                          : !hasChampion
                            ? 'Train a champion model first'
                            : scoreResultLoading || activeScoreRun
                              ? 'Scoring'
                              : undefined,
                      onSelect: () => scoreNow(),
                      pinned: {
                          order: 1,
                          variant: 'primary',
                          dataAttr: 'autoresearch-model-score',
                          render: () => <QuillScoreNowButton />,
                      },
                  },
              ] satisfies SceneAction[])
            : []),
        ...(paused || running
            ? ([
                  {
                      group: 'edit',
                      section: 'state',
                      id: paused ? `${RESOURCE_TYPE}-menubar-resume` : `${RESOURCE_TYPE}-menubar-pause`,
                      label: paused ? 'Resume' : 'Pause',
                      icon: paused ? <IconPlay /> : <IconPause />,
                      disabledReason: pipelineLoading ? 'Loading model' : undefined,
                      onSelect: () => (paused ? resumePipeline() : pausePipeline()),
                      pinned: {
                          order: 2,
                          variant: 'secondary',
                          dataAttr: paused ? 'autoresearch-model-resume' : 'autoresearch-model-pause',
                          render: () => <QuillPipelineActions />,
                      },
                  },
              ] satisfies SceneAction[])
            : []),
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
