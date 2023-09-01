import './featureFlags.scss'

import { useActions, useValues } from 'kea'
import { featureFlagsLogic } from '~/toolbar/flags/featureFlagsLogic'
import { AnimatedCollapsible } from 'lib/components/AnimatedCollapsible'
import { toolbarLogic } from '~/toolbar/toolbarLogic'
import { urls } from 'scenes/urls'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'
import clsx from 'clsx'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch/LemonSwitch'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { LemonCheckbox } from 'lib/lemon-ui/LemonCheckbox'
import { toolbarButtonLogic } from '~/toolbar/button/toolbarButtonLogic'

function OverrideNotice(): JSX.Element {
    return (
        <div className="local-feature-flag-override-note rounded border p-2 my-2">
            Note, overriding feature flags will only affect this browser.
        </div>
    )
}

export function FeatureFlags(): JSX.Element {
    const { searchTerm, filteredFlags, userFlagsLoading } = useValues(featureFlagsLogic)
    const { setOverriddenUserFlag, deleteOverriddenUserFlag, setSearchTerm } = useActions(featureFlagsLogic)
    const { apiURL } = useValues(toolbarLogic)
    const { hedgehogMode } = useValues(toolbarButtonLogic)

    return (
        <div
            className={clsx('toolbar-block ToolbarBlock w-full overflow-hidden rounded-t', hedgehogMode && 'px-2 py-1')}
        >
            <>
                {hedgehogMode && <OverrideNotice />}
                <LemonInput
                    autoFocus
                    placeholder="Search"
                    fullWidth
                    type={'search'}
                    value={searchTerm}
                    className={clsx('feature-flag-row', !hedgehogMode && 'rounded-b-0')}
                    onChange={(s) => setSearchTerm(s)}
                />
                <div className={'flex flex-col w-full space-y-1 py-2 relative overflow-y-scroll'}>
                    {filteredFlags.length > 0 ? (
                        filteredFlags.map(({ feature_flag, value, hasOverride, hasVariants, currentValue }) => (
                            <div className={'feature-flag-row FeatureFlagRow'} key={feature_flag.key}>
                                <div
                                    className={clsx(
                                        'flex flex-row items-center px-2',
                                        hasOverride && 'overridden',
                                        'feature-flag-row-header FeatureFlagRow__header'
                                    )}
                                >
                                    <div className="flex-1 font-bold truncate">{feature_flag.key}</div>
                                    <a
                                        className="feature-flag-external-link mx-4"
                                        href={`${apiURL}${
                                            feature_flag.id ? urls.featureFlag(feature_flag.id) : urls.featureFlags()
                                        }`}
                                        target="_blank"
                                        rel="noopener noreferrer"
                                    >
                                        <IconOpenInNew />
                                    </a>
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
                                                    currentValue === variant.key &&
                                                        'font-bold rounded bg-primary-highlight',
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
                </div>
            </>
            {!hedgehogMode && <OverrideNotice />}
        </div>
    )
}
