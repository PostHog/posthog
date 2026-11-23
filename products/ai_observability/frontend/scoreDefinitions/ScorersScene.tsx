import type { ReactNode } from 'react'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { EvaluationsTabs } from '../evaluations/EvaluationsTabs'

export function ScorersScene({ children }: { children: ReactNode }): JSX.Element {
    return (
        <SceneContent>
            <SceneTitleSection
                name="Evaluations"
                description="Manage score definitions and versions for manual reviews and offline evaluations."
                resourceType={{ type: 'llm_evaluations' }}
            />
            <EvaluationsTabs activeTab="scorers">{children}</EvaluationsTabs>
        </SceneContent>
    )
}
