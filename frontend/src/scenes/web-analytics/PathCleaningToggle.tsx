import { useValues } from 'kea'

import { IconGear } from '@posthog/icons'
import { LemonButton, LemonSwitch, Link, Tooltip } from '@posthog/lemon-ui'
import { Button, Switch } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { IconBranch } from 'lib/lemon-ui/icons/icons'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { AvailableFeature } from '~/types'

export const PathCleaningToggle = ({
    value,
    onChange,
}: {
    value: boolean
    onChange: (enabled: boolean) => void
}): JSX.Element | null => {
    const { hasAvailableFeature } = useValues(userLogic)
    const hasAdvancedPaths = hasAvailableFeature(AvailableFeature.PATHS_ADVANCED)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (!hasAdvancedPaths) {
        return null
    }

    return (
        <Tooltip
            title={
                <div className="p-2">
                    <p className="mb-2">
                        Path cleaning helps standardize URLs by removing unnecessary parameters and fragments.
                    </p>
                    <div className="mb-2">
                        <Link to="https://posthog.com/docs/product-analytics/paths#path-cleaning-rules">
                            Learn more about path cleaning rules
                        </Link>
                    </div>
                    <LemonButton
                        icon={<IconGear />}
                        type="primary"
                        size="small"
                        to={urls.settings('project-product-analytics', 'path-cleaning')}
                        targetBlank
                        className="w-full"
                    >
                        Edit path cleaning settings
                    </LemonButton>
                </div>
            }
            placement="top"
            interactive={true}
        >
            {todayRailNav ? (
                <Button variant="outline" onClick={() => onChange(!value)} aria-pressed={value}>
                    <IconBranch />
                    Path cleaning
                    {/* Decorative: the button owns the toggle, so the switch must not take clicks or focus. */}
                    <Switch checked={value} size="sm" tabIndex={-1} aria-hidden className="pointer-events-none ml-1" />
                </Button>
            ) : (
                <LemonButton icon={<IconBranch />} onClick={() => onChange(!value)} type="secondary" size="small">
                    Path cleaning: <LemonSwitch checked={value} className="ml-1" />
                </LemonButton>
            )}
        </Tooltip>
    )
}
