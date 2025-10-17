import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { AnimatedCollapsible } from 'lib/components/AnimatedCollapsible'
import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { Link } from 'lib/lemon-ui/Link'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { IconOpenInNew } from 'lib/lemon-ui/icons'
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
        setPayloadEditorOpen,
    } = useActions(flagsToolbarLogic)
    const { apiURL, posthog: posthogClient } = useValues(toolbarConfigLogic)
    const { openPayloadEditors } = useValues(flagsToolbarLogic)

    useOnMountEffect(() => {
        posthogClient?.onFeatureFlags(setFeatureFlagValueFromPostHogClient)
        getUserFlags()
        checkLocalOverrides()
    })

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
                                    <div className="flex flex-row items-center deprecated-space-x-2">
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
                                        <LemonButton
                                            size="xsmall"
                                            type="secondary"
                                            onClick={() => setPayloadEditorOpen(feature_flag.key, true)}
                                            disabledReason={
                                                currentValue ? undefined : 'Cannot edit payload while flag is disabled'
                                            }
                                        >
                                            Edit payload
                                        </LemonButton>
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
                                                            label: `${variant.key}${
                                                                variant.name ? ` - ${variant.name}` : ''
                                                            } (${variant.rollout_percentage}%)`,
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

                                            <div className={clsx(hasVariants && 'py-1 pl-4')}>
                                                {openPayloadEditors[feature_flag.key] ? (
                                                    <div className="flex gap-2 items-start mt-1">
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
                                                            onChange={(val) => setDraftPayload(feature_flag.key, val)}
                                                            placeholder='Examples: "A string", 2500, {"key": "value"}'
                                                            minRows={2}
                                                        />
                                                        <div className="flex flex-col gap-1">
                                                            <LemonButton
                                                                size="xsmall"
                                                                type="primary"
                                                                onClick={() => savePayloadOverride(feature_flag.key)}
                                                                center
                                                            >
                                                                Save
                                                            </LemonButton>
                                                            <LemonButton
                                                                size="xsmall"
                                                                onClick={() =>
                                                                    setPayloadEditorOpen(feature_flag.key, false)
                                                                }
                                                            >
                                                                Cancel
                                                            </LemonButton>
                                                        </div>
                                                    </div>
                                                ) : (
                                                    <div className="flex justify-end items-center gap-2">
                                                        {payloadOverride && (
                                                            <div className="font-mono text-xs truncate flex-1">
                                                                {JSON.stringify(payloadOverride)}
                                                            </div>
                                                        )}
                                                    </div>
                                                )}
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
