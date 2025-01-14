import { useActions, useValues } from 'kea'
import { DowngradeFeature, FeatureDowngradeModal } from 'lib/components/FeatureDowngradeModal/FeatureDowngradeModal'

import { teamsDowngradeLogic } from './teamsDowngradeLogic'

const TEAMS_FEATURES: DowngradeFeature[] = [
    {
        // Replace hardcoding here
        title: '2FA Enforcement',
    },
]

export function TeamsDowngradeModal(): JSX.Element {
    const { isTeamsDowngradeModalOpen } = useValues(teamsDowngradeLogic)
    const { hideTeamsDowngradeModal, handleTeamsDowngrade } = useActions(teamsDowngradeLogic)

    return (
        <FeatureDowngradeModal
            isOpen={isTeamsDowngradeModalOpen}
            onClose={hideTeamsDowngradeModal}
            onDowngrade={handleTeamsDowngrade}
            title="Unsubscribe from Teams"
            features={TEAMS_FEATURES}
        />
    )
}
