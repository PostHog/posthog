import { useActions, useValues } from 'kea'

import { IconPerson } from '@posthog/icons'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { ToolbarMenu } from '~/toolbar/floating/components/bar/ToolbarMenu'
import { FlagComparisonModal } from '~/toolbar/floating/components/flags/FlagComparisonModal'
import { FlagsImpersonationPanel } from '~/toolbar/floating/components/flags/FlagsImpersonationPanel'
import { FeatureFlagRow } from '~/toolbar/shared/flags/FeatureFlagRow'
import { FlagCompareButton } from '~/toolbar/shared/flags/FlagCompareButton'
import { flagComparisonLogic } from '~/toolbar/shared/flags/flagComparisonLogic'
import { toFlagInfo } from '~/toolbar/shared/flags/flagInfo'
import { flagsToolbarLogic } from '~/toolbar/shared/flags/flagsToolbarLogic'
import { toolbarConfigLogic } from '~/toolbar/shared/toolbarConfigLogic'
import { urls } from '~/toolbar/shared/urls'
import { joinWithUiHost } from '~/toolbar/shared/utils'

export const FlagsToolbarMenu = (): JSX.Element => {
    const {
        searchTerm,
        filteredFlags,
        userFlagsLoading,
        draftPayloads,
        payloadErrors,
        countFlagsOverridden,
        impersonatedDistinctId,
        impersonationOpen,
        openPayloadEditors,
    } = useValues(flagsToolbarLogic)
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
        clearAllOverrides,
        setImpersonationOpen,
    } = useActions(flagsToolbarLogic)
    const { uiHost, posthog: posthogClient, toolbarFlagsKey } = useValues(toolbarConfigLogic)
    const { comparingFlagKey } = useValues(flagComparisonLogic)
    const { compareFlag } = useActions(flagComparisonLogic)
    const comparingReason = comparingFlagKey ? 'Wait for the comparison to finish' : null

    useOnMountEffect(() => {
        posthogClient?.onFeatureFlags(setFeatureFlagValueFromPostHogClient)

        if (toolbarFlagsKey && posthogClient) {
            // When toolbarFlagsKey is present, flags were pre-loaded via overrideFeatureFlags

            // Read the current values directly and update state
            const currentFlags = posthogClient.featureFlags.getFlagVariants()
            setFeatureFlagValueFromPostHogClient(Object.keys(currentFlags), currentFlags)
        }

        getUserFlags()
        checkLocalOverrides()
    })

    return (
        <ToolbarMenu>
            <ToolbarMenu.Header>
                <div className="flex gap-2 items-center w-full pr-3">
                    <LemonInput
                        autoFocus
                        placeholder="Search"
                        fullWidth
                        type="search"
                        value={searchTerm}
                        onChange={(s) => setSearchTerm(s)}
                    />
                    <LemonButton
                        type="secondary"
                        size="small"
                        className="flex-shrink-0"
                        onClick={clearAllOverrides}
                        disabledReason={
                            comparingReason ?? (countFlagsOverridden === 0 ? 'No overrides to clear' : undefined)
                        }
                    >
                        Clear overrides
                    </LemonButton>
                    <LemonButton
                        className="flex-shrink-0"
                        size="small"
                        icon={<IconPerson />}
                        type={impersonatedDistinctId ? 'primary' : 'secondary'}
                        onClick={() => setImpersonationOpen(!impersonationOpen)}
                        tooltip="Load feature flags for a provided distinct ID"
                    />
                </div>
            </ToolbarMenu.Header>

            <ToolbarMenu.Body>
                <div className="mt-1">
                    {filteredFlags.length > 0 ? (
                        <div className="flex flex-col gap-px">
                            {filteredFlags.map((filteredFlag) => {
                                const flag = toFlagInfo(filteredFlag)
                                const { key, id } = flag
                                return (
                                    <FeatureFlagRow
                                        key={key}
                                        flag={flag}
                                        flagUrl={joinWithUiHost(
                                            uiHost,
                                            id ? urls.featureFlag(id) : urls.featureFlags()
                                        )}
                                        payloadDraft={openPayloadEditors[key] ? (draftPayloads[key] ?? '') : null}
                                        payloadError={payloadErrors[key] ?? null}
                                        disabledReason={comparingReason}
                                        onSetOverride={(value) => setOverriddenUserFlag(key, value)}
                                        onRemoveOverride={() => deleteOverriddenUserFlag(key)}
                                        onOpenPayloadEditor={(initialDraft) => {
                                            setDraftPayload(key, initialDraft)
                                            setPayloadEditorOpen(key, true)
                                        }}
                                        onPayloadDraftChange={(draft) => setDraftPayload(key, draft)}
                                        onSavePayload={() => savePayloadOverride(key)}
                                        onClosePayloadEditor={() => setPayloadEditorOpen(key, false)}
                                        actions={
                                            <FlagCompareButton
                                                comparing={comparingFlagKey === key}
                                                disabledReason={
                                                    comparingReason ??
                                                    (posthogClient ? null : 'The page has no PostHog client')
                                                }
                                                onCompare={() => compareFlag(flag)}
                                                dataAttr="toolbar-flag-compare"
                                            />
                                        }
                                        dataAttrPrefix="toolbar-flag"
                                    />
                                )
                            })}
                        </div>
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
                <div className="flex flex-col gap-1 w-full">
                    <FlagsImpersonationPanel disabledReason={comparingReason} />
                    <span className="text-xs">
                        Note: overriding feature flags and payloads will only affect this browser.
                    </span>
                </div>
            </ToolbarMenu.Footer>
            <FlagComparisonModal />
        </ToolbarMenu>
    )
}
