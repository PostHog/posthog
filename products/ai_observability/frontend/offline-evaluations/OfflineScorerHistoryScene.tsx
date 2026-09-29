import { useValues } from 'kea'

import { LemonBanner, Spinner } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import type { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'

import { ProductKey } from '~/queries/schema/schema-general'

import { OfflineScorerHistory } from './OfflineScorerHistory'
import type { OfflineScorerHistoryProps } from './offlineScorerHistoryLogic'

export const scene: SceneExport<Pick<OfflineScorerHistoryProps, 'scorerId'>> = {
    component: OfflineScorerHistoryScene,
    productKey: ProductKey.AI_OBSERVABILITY,
    paramsToProps: ({ params: { scorerId } }) => ({ scorerId }),
}

export function OfflineScorerHistoryScene(props: Pick<OfflineScorerHistoryProps, 'scorerId'>): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { currentTeamId } = useValues(teamLogic)
    return featureFlags[FEATURE_FLAGS.AI_OBSERVABILITY_OFFLINE_EVALUATIONS] ? (
        currentTeamId ? (
            <OfflineScorerHistory key={`${currentTeamId}:${props.scorerId}`} {...props} teamId={currentTeamId} />
        ) : (
            <Spinner />
        )
    ) : (
        <LemonBanner type="info">Offline evals are not available for this project.</LemonBanner>
    )
}
