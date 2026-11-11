import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { Link } from 'lib/lemon-ui/Link'
import { getFeatureFlagPayload } from 'lib/logic/featureFlagLogic'
import { isHttpsUrl } from 'lib/utils/url'

export function HiddenEventExplanation(): JSX.Element {
    const moveNoticesEnabled = useFeatureFlag('FLAG_CALLED_MOVE_NOTICES')
    const payloadUrl = moveNoticesEnabled ? getFeatureFlagPayload(FEATURE_FLAGS.FLAG_CALLED_MOVE_NOTICES)?.url : null
    // isHttpsUrl ignores surrounding whitespace. Link turns a value with a leading space into an in-app path.
    const announcementUrl = typeof payloadUrl === 'string' && isHttpsUrl(payloadUrl) ? payloadUrl.trim() : null

    return (
        <>
            PostHog still collects this event, but you can't build a saved query on it. Its data is moving, so a saved
            query would stop returning results. To see how a flag is used, open the flag and check its Usage tab.
            {announcementUrl && (
                <>
                    {' '}
                    <Link to={announcementUrl} target="_blank" data-attr="taxonomic-hidden-event-announcement">
                        Learn more
                    </Link>
                </>
            )}
        </>
    )
}
