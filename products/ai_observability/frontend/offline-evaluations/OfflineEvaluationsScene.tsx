import type { ReactNode } from 'react'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { EvaluationsTabs } from '../evaluations/EvaluationsTabs'

export function OfflineEvaluationsScene({ children }: { children: ReactNode }): JSX.Element {
    return (
        <SceneContent>
            <SceneTitleSection
                name="Evaluations"
                description="Manage datasets, follow score trends, and inspect offline experiment results."
                resourceType={{ type: 'llm_evaluations' }}
            />
            <EvaluationsTabs activeTab="offline-evals">{children}</EvaluationsTabs>
        </SceneContent>
    )
}
