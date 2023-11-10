import { ToolbarMenu } from '~/toolbar/3000/ToolbarMenu'
import { HTMLAttributes } from 'react'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { featureFlagsLogic } from '~/toolbar/flags/featureFlagsLogic'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { urls } from 'scenes/urls'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { AnimatedCollapsible } from 'lib/components/AnimatedCollapsible'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { Link } from 'lib/lemon-ui/Link'

const MenuHeader = (): JSX.Element => {
    const { searchTerm } = useValues(featureFlagsLogic)
    const { setSearchTerm } = useActions(featureFlagsLogic)

    return (
        <LemonInput
            autoFocus
            placeholder="Search"
            fullWidth
            type={'search'}
            value={searchTerm}
            rounded={'top'}
            onChange={(s) => setSearchTerm(s)}
        />
    )
}

const MenuBody = (): JSX.Element => {
    const { searchTerm, filteredFlags, userFlagsLoading } = useValues(featureFlagsLogic)
    const { setOverriddenUserFlag, deleteOverriddenUserFlag } = useActions(featureFlagsLogic)
    const { apiURL } = useValues(toolbarLogic)
    return (
        <>
            {filteredFlags.length > 0 ? (
                filteredFlags.map(({ feature_flag, value, hasOverride, hasVariants, currentValue }) => (
                    <div
                        className={clsx('FeatureFlagRow', hasOverride && 'FeatureFlagRow__overridden')}
                        key={feature_flag.key}
                    >
                        <div className={clsx('flex flex-row items-center', 'FeatureFlagRow__header', 'py-1')}>
                            <div className="flex-1 truncate">
                                <Link
                                    className="text-text-3000 flex flex-row items-center"
                                    to={`${apiURL}${
                                        feature_flag.id ? urls.featureFlag(feature_flag.id) : urls.featureFlags()
                                    }`}
                                    target="_blank"
                                >
                                    {feature_flag.key}
                                    <IconOpenInNew />
                                </Link>
                            </div>

                            <LemonSwitch
                                checked={!!currentValue}
                                onChange={(checked) => {
                                    const newValue =
                                        hasVariants && checked
                                            ? (feature_flag.filters?.multivariate?.variants[0]?.key as string)
                                            : checked
                                    if (newValue === value && hasOverride) {
                                        deleteOverriddenUserFlag(feature_flag.key)
                                    } else {
                                        setOverriddenUserFlag(feature_flag.key, newValue)
                                    }
                                }}
                            />
                        </div>

                        <AnimatedCollapsible collapsed={!hasVariants || !currentValue}>
                            <div
                                className={clsx(
                                    'variant-radio-group flex flex-col w-full px-4 py-2 ml-8',
                                    hasOverride && 'overridden'
                                )}
                            >
                                {feature_flag.filters?.multivariate?.variants.map((variant) => (
                                    <LemonCheckbox
                                        key={variant.key}
                                        fullWidth
                                        checked={currentValue === variant.key}
                                        label={`${variant.key} - ${variant.name} (${variant.rollout_percentage}%)`}
                                        onChange={() => {
                                            const newValue = variant.key
                                            if (newValue === value && hasOverride) {
                                                deleteOverriddenUserFlag(feature_flag.key)
                                            } else {
                                                setOverriddenUserFlag(feature_flag.key, newValue)
                                            }
                                        }}
                                        className={clsx(
                                            currentValue === variant.key && 'font-bold rounded bg-primary-highlight',
                                            'px-2 py-1'
                                        )}
                                    />
                                ))}
                            </div>
                        </AnimatedCollapsible>
                    </div>
                ))
            ) : (
                <div className={'FeatureFlagRow flex flex-row items-center px-2 py-1'}>
                    {userFlagsLoading ? (
                        <Spinner className={'text-2xl'} />
                    ) : (
                        `No ${searchTerm.length ? 'matching ' : ''}feature flags found.`
                    )}
                </div>
            )}
        </>
    )
}

const MenuFooter = ({ className }: Pick<HTMLAttributes<HTMLDivElement>, 'className'>): JSX.Element => {
    return (
        <div className={clsx('px-2 py-1 text-xs', className)}>
            Note: overriding feature flags will only affect this browser.
        </div>
    )
}

export const FlagsToolbarMenu = (): JSX.Element => {
    return <ToolbarMenu header={<MenuHeader />} body={<MenuBody />} footer={<MenuFooter />} />
}
