import { useActions, useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { activityClientLabel } from 'lib/components/ActivityLog/activityClientLabel'
import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import { Experiment, FeatureFlagBasicType } from '~/types'

import { FeatureFlagDeletedBanner } from 'products/feature_flags/frontend/FeatureFlagDeletedBanner'

import { experimentLogic } from '../experimentLogic'
import { deletedFlagBannerLogic } from './deletedFlagBannerLogic'

function DeletedFlagBannerContent({
    experimentId,
    flag,
    flagKey,
}: {
    experimentId: Experiment['id']
    flag: FeatureFlagBasicType
    /** The key people know the flag by, from before the delete renamed it. */
    flagKey: Experiment['feature_flag_key']
}): JSX.Element | null {
    const logic = deletedFlagBannerLogic({ experimentId, flagId: flag.id })
    const { deletedFlag, deletedFlagLoading, flagDeletion, restoredFlagLoading } = useValues(logic)
    const { restoreFlag } = useActions(logic)

    // Until the flag API answers, nobody knows whether the viewer can restore the flag.
    if (deletedFlagLoading) {
        return null
    }

    return (
        <FeatureFlagDeletedBanner
            // When the flag API can't be read, the banner offers no restore.
            flag={deletedFlag ?? { ...flag, archived: false, can_edit: false }}
            subject={
                <>
                    This experiment's feature flag{' '}
                    <Link to={urls.featureFlag(flag.id)} target="_blank">
                        {flagKey}
                    </Link>
                </>
            }
            onRestore={restoreFlag}
            restoreLoading={restoredFlagLoading}
            restoreDataAttr="experiment-restore-deleted-flag"
            className="mb-4"
        >
            <div>
                {flagDeletion && (
                    <>
                        {flagDeletion.actor} deleted it <TZLabel time={flagDeletion.deletedAt} />
                        {flagDeletion.client ? ` via ${activityClientLabel(flagDeletion.client)}` : ''}.{' '}
                    </>
                )}
                The experiment can't launch until the flag is restored.
            </div>
        </FeatureFlagDeletedBanner>
    )
}

/** A draft can't launch on a deleted flag. Once an experiment has run, deleting its flag is the normal cleanup. */
export function DeletedFlagBanner(): JSX.Element | null {
    const { experiment, isExperimentDraft } = useValues(experimentLogic)
    const flag = experiment.feature_flag

    if (!flag?.deleted || !isExperimentDraft) {
        return null
    }

    // Deleting a flag adds `:deleted:<id>` to its key. The experiment API strips that suffix from `feature_flag_key`.
    return <DeletedFlagBannerContent experimentId={experiment.id} flag={flag} flagKey={experiment.feature_flag_key} />
}
