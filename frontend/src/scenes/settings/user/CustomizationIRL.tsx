import { Link } from '@posthog/lemon-ui'
import { Button, Text } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

const MERCH_URL = 'https://posthog.com/merch'

export function CustomizationIRL(): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return (
            <Text size="xs" render={<p className="m-0" />}>
                Grab some{' '}
                <Button
                    variant="link"
                    size="inline"
                    nativeButton={false}
                    render={<LinkPrimitive to={MERCH_URL} target="_blank" />}
                >
                    PostHog merch
                </Button>{' '}
                to customize yourself outside of the app
            </Text>
        )
    }

    return (
        <div>
            Grab some{' '}
            <Link to={MERCH_URL} target="_blank">
                PostHog merch
            </Link>{' '}
            to customize yourself outside of the app
        </div>
    )
}
