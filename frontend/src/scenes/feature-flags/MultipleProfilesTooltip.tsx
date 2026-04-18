import { IconInfo } from '@posthog/icons'
import { Link, Tooltip } from '@posthog/lemon-ui'

export const MULTIPLE_PROFILES_TOOLTIP_TEXT =
    'This is the number of matching person profiles. A single user may have multiple profiles (e.g. one per device, or before logging in), so this can be higher than the number of distinct end users.'

export function MultipleProfilesTooltip(): JSX.Element {
    return (
        <Tooltip
            title={
                <>
                    {MULTIPLE_PROFILES_TOOLTIP_TEXT}{' '}
                    <Link to="https://posthog.com/docs/data/persons#duplicate-person-profiles" target="_blank">
                        Learn more
                    </Link>
                </>
            }
            interactive
        >
            <IconInfo className="text-muted text-xs ml-0.5" />
        </Tooltip>
    )
}
