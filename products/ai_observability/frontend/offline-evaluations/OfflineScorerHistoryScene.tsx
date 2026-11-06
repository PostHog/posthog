import { useValues } from 'kea'

import { Spinner } from '@posthog/lemon-ui'

import type { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { OfflineEvaluationsGate } from './OfflineEvaluationsGate'
import { OfflineScorerHistory } from './OfflineScorerHistory'
import type { OfflineScorerHistoryProps } from './offlineScorerHistoryLogic'

export const scene: SceneExport<Pick<OfflineScorerHistoryProps, 'scorerId'>> = {
    component: OfflineScorerHistoryScene,
    productKey: ProductKey.AI_OBSERVABILITY,
    paramsToProps: ({ params: { scorerId } }) => ({ scorerId }),
}

export function OfflineScorerHistoryScene(props: Pick<OfflineScorerHistoryProps, 'scorerId'>): JSX.Element {
    const { currentTeamId } = useValues(teamLogic)
    return (
        <OfflineEvaluationsGate>
            {currentTeamId ? (
                <OfflineScorerHistory key={`${currentTeamId}:${props.scorerId}`} {...props} teamId={currentTeamId} />
            ) : (
                <Spinner />
            )}
        </OfflineEvaluationsGate>
    )
}
