import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { AnimatedCollapsible } from 'lib/components/AnimatedCollapsible'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { urls } from 'scenes/urls'

import { ToolbarMenu } from '~/toolbar/bar/ToolbarMenu'
import { featureFlagsLogic } from '~/toolbar/flags/featureFlagsLogic'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'

export const FlagsToolbarMenu = (): JSX.Element => {
    const { searchTerm, filteredFlags, userFlagsLoading } = useValues(featureFlagsLogic)
    const { setSearchTerm, setOverriddenUserFlag, deleteOverriddenUserFlag } = useActions(featureFlagsLogic)
    const { apiURL } = useValues(toolbarConfigLogic)

    return (
        <ToolbarMenu>
            <ToolbarMenu.Header>
                <LemonInput
                    autoFocus
                    placeholder="Search"
                    fullWidth
                    type="search"
                    value={searchTerm}
                    onChange={(s) => setSearchTerm(s)}
                />
            </ToolbarMenu.Header>

            <ToolbarMenu.Body>
                <div className="mt-1">
                    {filteredFlags.length > 0 ? (
                        filteredFlags.map(({ feature_flag, value, hasOverride, hasVariants, currentValue }) => (
                            <div className={clsx('-mx-1 py-1 px-2', hasOverride && 'bg-mark')} key={feature_flag.key}>
                                <div className="flex flex-row items-center">
                                    <div className="flex-1 truncate">
                                        <Link
                                            className="font-medium"
                                            to={`${apiURL}${
                                                feature_flag.id
                                                    ? urls.featureFlag(feature_flag.id)
                                                    : urls.featureFlags()
                                            }`}
                                            subtle
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
                                    <LemonRadio
                                        className={clsx('pt-1 w-full', hasOverride && 'bg-mark')}
                                        value={typeof currentValue === 'string' ? currentValue : undefined}
                                        options={
                                            feature_flag.filters?.multivariate?.variants.map((variant) => ({
                                                label: `${variant.key} - ${variant.name} (${variant.rollout_percentage}%)`,
                                                value: variant.key,
                                            })) || []
                                        }
                                        onChange={(newValue) => {
                                            if (newValue === value && hasOverride) {
                                                deleteOverriddenUserFlag(feature_flag.key)
                                            } else {
                                                setOverriddenUserFlag(feature_flag.key, newValue)
                                            }
                                        }}
                                    />
                                </AnimatedCollapsible>
                            </div>
                        ))
                    ) : (
                        <div className="flex flex-row items-center p-1">
                            {userFlagsLoading ? (
                                <span className="flex-1 flex justify-center items-center p-4">
                                    <Spinner className="text-2xl" />
                                </span>
                            ) : (
                                `No ${searchTerm.length ? 'matching ' : ''}feature flags found in the project.`
                            )}
                        </div>
                    )}
                </div>
            </ToolbarMenu.Body>

            <ToolbarMenu.Footer>
                <span className="text-xs">Note: overriding feature flags will only affect this browser.</span>
            </ToolbarMenu.Footer>
        </ToolbarMenu>
    )
}
