import { IconTestTube } from '@posthog/icons'
import { LemonTag } from '@posthog/lemon-ui'

import { Tooltip } from 'lib/lemon-ui/Tooltip'

const DOCS_LINK = 'https://posthog.com/docs/data/persons/internal-test-users'

const TOOLTIP_TITLE = (
    <>
        Flagged as an internal or test user via the <code>$internal_or_test_user</code> property, typically set
        automatically by the PostHog JS SDK on localhost.
    </>
)

export function TestOrInternalUserTag(): JSX.Element {
    return (
        <Tooltip title={TOOLTIP_TITLE} docLink={DOCS_LINK}>
            <LemonTag type="caution" icon={<IconTestTube />}>
                Test user
            </LemonTag>
        </Tooltip>
    )
}

export function TestOrInternalUserIcon({ className }: { className?: string }): JSX.Element {
    return (
        <Tooltip title={TOOLTIP_TITLE} docLink={DOCS_LINK}>
            <IconTestTube className={className ?? 'ml-1 shrink-0'} />
        </Tooltip>
    )
}
