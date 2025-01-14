import { useActions, useValues } from 'kea'
import { DowngradeFeature, FeatureDowngradeModal } from 'lib/components/FeatureDowngradeModal/FeatureDowngradeModal'

import { AvailableFeature } from '~/types'

import { teamsDowngradeLogic } from './teamsDowngradeLogic'

export function TeamsDowngradeModal(): JSX.Element {
    const { isTeamsDowngradeModalOpen, enforce2FA } = useValues(teamsDowngradeLogic)
    const { hideTeamsDowngradeModal, handleTeamsDowngrade } = useActions(teamsDowngradeLogic)

    const teamFeatures: DowngradeFeature[] = []

    if (enforce2FA) {
        teamFeatures.push({
            title: AvailableFeature.TWOFA_ENFORCEMENT,
        })
    }

    return (
        <FeatureDowngradeModal
            isOpen={isTeamsDowngradeModalOpen}
            onClose={hideTeamsDowngradeModal}
            onDowngrade={handleTeamsDowngrade}
            title="Unsubscribe from Teams"
            features={teamFeatures}
        />
    )
}
