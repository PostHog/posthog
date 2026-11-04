import { useValues } from 'kea'

import { IconWarning } from '@posthog/icons'

import { showsFlagCalledMoveNotice } from 'lib/components/FlagCalledMoveNotice/showsFlagCalledMoveNotice'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { Link } from 'lib/lemon-ui/Link'
import { featureFlagLogic, getFeatureFlagPayload } from 'lib/logic/featureFlagLogic'
import { cn } from 'lib/utils/css-classes'
import { isHttpsUrl } from 'lib/utils/url'
import { teamLogic } from 'scenes/teamLogic'

interface FlagCalledMoveNoticeProps {
    name: string | null | undefined
    groupType: TaxonomicFilterGroupType
    className?: string
}

// Remove once every organization is on flag_evaluations_mode 2 (#88126). Delete this folder and its render sites
// together. Other move warnings also read FEATURE_FLAGS.FLAG_CALLED_MOVE_NOTICES, so delete the constant only after
// the last of them is gone.
export function FlagCalledMoveNotice({ name, groupType, className }: FlagCalledMoveNoticeProps): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const { currentTeam } = useValues(teamLogic)

    if (
        !featureFlags[FEATURE_FLAGS.FLAG_CALLED_MOVE_NOTICES] ||
        !showsFlagCalledMoveNotice(name, groupType, currentTeam?.flag_evaluations_mode)
    ) {
        return null
    }

    const announcementUrl = getFeatureFlagPayload(FEATURE_FLAGS.FLAG_CALLED_MOVE_NOTICES)?.url

    return (
        <div className={cn('flex items-start gap-1.5', className)} data-attr="flag-called-move-notice">
            <IconWarning className="shrink-0 mt-0.5 text-warning" />
            <span>
                <code>$feature_flag_called</code> is moving from <code>events</code> to{' '}
                <code>posthog.flag_evaluations</code>. Once the move finishes for your organization, insights and
                queries on this event will stop returning results, and you can query{' '}
                <code>posthog.flag_evaluations</code> instead.
                {typeof announcementUrl === 'string' && isHttpsUrl(announcementUrl) && (
                    <>
                        {' '}
                        <Link to={announcementUrl} target="_blank" data-attr="flag-called-move-notice-announcement">
                            Learn more
                        </Link>
                    </>
                )}
            </span>
        </div>
    )
}
