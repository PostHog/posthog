import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { AnimatedCollapsible } from 'lib/components/AnimatedCollapsible'
import { IconOpenInNew } from '@posthog/lemon-ui/icons'
import { LemonButton } from '@posthog/lemon-ui/LemonButton'
import { LemonInput } from '@posthog/lemon-ui/LemonInput'
import { LemonRadio } from '@posthog/lemon-ui/LemonRadio'
import { LemonSwitch } from '@posthog/lemon-ui/LemonSwitch'
import { LemonTextArea } from '@posthog/lemon-ui/LemonTextArea'
import { Link } from '@posthog/lemon-ui/Link'
import { Spinner } from '@posthog/lemon-ui/Spinner'
import { debounce } from 'lib/utils'
import { useEffect, useMemo } from 'react'
import { urls } from 'scenes/urls'

import { ToolbarMenu } from '~/toolbar/bar/ToolbarMenu'
import { flagsToolbarLogic } from '~/toolbar/flags/flagsToolbarLogic'
import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'

export const FlagsToolbarMenu = (): JSX.Element => {
    const { searchTerm, filteredFlags, userFlagsLoading, draftPayloads, payloadErrors } = useValues(flagsToolbarLogic)
    const {
        setSearchTerm,
        setOverriddenUserFlag,
        deleteOverriddenUserFlag,
        getUserFlags,
        checkLocalOverrides,
        setFeatureFlagValueFromPostHogClient,
        setDraftPayload,
        savePayloadOverride,
    } = useActions(flagsToolbarLogic)
    const { apiURL, posthog: posthogClient } = useValues(toolbarConfigLogic)

    const debouncedSetDraftPayload = useMemo(
        () => debounce((key: string, value: string) => setDraftPayload(key, value), 300),
        [setDraftPayload]
    )

    useEffect(() => {
        posthogClient?.onFeatureFlags(setFeatureFlagValueFromPostHogClient)
        getUserFlags()
        checkLocalOverrides()
    }, [])

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
                        filteredFlags.map(
                            ({ feature_flag, value, hasOverride, hasVariants, currentValue, payloadOverride }) => (
                                <div
                                    className={clsx('-mx-1 py-1 px-2', hasOverride && 'bg-fill-primary')}
                                    key={feature_flag.key}
                                >
                                    <div className="flex flex-row items-center">
                                        <div className="flex-1 truncate">
                                            <Link
                                                className="font-medium"
                                                to={`${apiURL}${feature_flag.id
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
                                                        ? (feature_flag.filters?.multivariate?.variants[0]
                                                            ?.key as string)
                                                        : checked
                                                if (newValue === value && hasOverride) {
                                                    deleteOverriddenUserFlag(feature_flag.key)
                                                } else {
                                                    setOverriddenUserFlag(feature_flag.key, newValue)
                                                }
                                            }}
                                        />
                                    </div>

                                    <AnimatedCollapsible collapsed={!currentValue}>
                                        <>
                                            {hasVariants ? (
                                                <LemonRadio
                                                    className={clsx('pt-1 pl-4 w-full', hasOverride && 'bg-mark')}
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
                                            ) : null}

                                            <div className={clsx('py-1', hasVariants && 'pl-4')}>
                                                <label className="text-xs font-semibold">Payload</label>
                                                <div className="flex gap-2 items-center mt-1">
                                                    <LemonTextArea
                                                        className={clsx(
                                                            'font-mono text-xs flex-1 !rounded',
                                                            payloadErrors[feature_flag.key] && 'border-danger'
                                                        )}
                                                        value={
                                                            draftPayloads[feature_flag.key] ??
                                                            (payloadOverride
                                                                ? JSON.stringify(payloadOverride, null, 2)
                                                                : '')
                                                        }
                                                        onChange={(val) =>
                                                            debouncedSetDraftPayload(feature_flag.key, val)
                                                        }
                                                        placeholder='{"key": "value"}'
                                                        minRows={2}
                                                    />
                                                    <LemonButton
                                                        size="small"
                                                        type="primary"
                                                        onClick={() => savePayloadOverride(feature_flag.key)}
                                                    >
                                                        Save
                                                    </LemonButton>
                                                </div>
                                            </div>
                                        </>
                                    </AnimatedCollapsible>
                                </div>
                            )
                        )
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
                <span className="text-xs">
                    Note: overriding feature flags and payloads will only affect this browser.
                </span>
            </ToolbarMenu.Footer>
        </ToolbarMenu>
    )
}
