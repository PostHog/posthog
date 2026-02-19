import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonLabel, LemonSegmentedButton, LemonSegmentedButtonOption, Tooltip } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'

import { AccessControlLevel, MultivariateFlagOptions } from '~/types'

import { ingestionControlsLogic } from '../../ingestionControlsLogic'
import { flagTriggerLogic } from './flagTriggerLogic'

export const ANY_VARIANT = 'any'

export function variantOptions(
    multivariate: MultivariateFlagOptions | undefined,
    disabledReason?: string | null
): LemonSegmentedButtonOption<string>[] {
    if (!multivariate) {
        return []
    }
    return [
        {
            label: ANY_VARIANT,
            value: ANY_VARIANT,
            disabledReason: disabledReason ?? undefined,
        },
        ...multivariate.variants.map((variant) => {
            return {
                label: variant.key,
                value: variant.key,
                disabledReason: disabledReason ?? undefined,
            }
        }),
    ]
}

export const FlagTriggerVariantSelector = ({ tooltip }: { tooltip: JSX.Element }): JSX.Element | null => {
    const { resourceType } = useValues(ingestionControlsLogic)
    const { flag, featureFlagLoading, linkedFlag, flagHasVariants } = useValues(flagTriggerLogic)
    const { onChange } = useActions(flagTriggerLogic)

    if (!flagHasVariants) {
        return null
    }

    return (
        <>
            <LemonLabel className="text-base">
                Link to a specific flag variant{' '}
                <Tooltip delayMs={200} title={tooltip}>
                    <IconInfo className="text-muted-alt cursor-help" />
                </Tooltip>
            </LemonLabel>
            <AccessControlAction resourceType={resourceType} minAccessLevel={AccessControlLevel.Editor}>
                {({ disabledReason }) => (
                    <LemonSegmentedButton
                        className="min-w-1/3"
                        value={flag?.variant ?? ANY_VARIANT}
                        options={variantOptions(
                            linkedFlag?.filters.multivariate,
                            (disabledReason ?? featureFlagLoading) ? 'Loading...' : undefined
                        )}
                        onChange={(variant) => {
                            if (!linkedFlag) {
                                return
                            }

                            onChange({
                                id: linkedFlag?.id,
                                key: linkedFlag?.key,
                                variant: variant === ANY_VARIANT ? null : variant,
                            })
                        }}
                    />
                )}
            </AccessControlAction>
        </>
    )
}
