import { useActions, useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { activityClientLabel } from 'lib/components/ActivityLog/activityClientLabel'
import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import { Experiment, FeatureFlagBasicType } from '~/types'

import { FeatureFlagDeletedBanner } from 'products/feature_flags/frontend/FeatureFlagDeletedBanner'

import { experimentLogic } from '../experimentLogic'
import { deletedFlagBannerLogic } from './deletedFlagBannerLogic'

// Deleting a flag that an experiment uses renames its key to `<key>:deleted:<id>`. People know the flag by the original key.
function keyBeforeDelete(flag: FeatureFlagBasicType): string {
    const suffix = `:deleted:${flag.id}`
    return flag.key.endsWith(suffix) ? flag.key.slice(0, -suffix.length) : flag.key
}

function DeletedFlagBannerContent({
    experimentId,
    flag,
}: {
    experimentId: Experiment['id']
    flag: FeatureFlagBasicType
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
                        {keyBeforeDelete(flag)}
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

    return <DeletedFlagBannerContent experimentId={experiment.id} flag={flag} />
}
