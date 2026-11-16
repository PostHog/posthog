import { useActions, useValues } from 'kea'

import { IconPerson, IconRefresh } from '@posthog/icons'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonInput } from 'lib/lemon-ui/LemonInput'

import { FeatureFlagRow } from '~/toolbar/shared/flags/FeatureFlagRow'
import { urls } from '~/toolbar/shared/urls'

import { extensionFlagsLogic } from '../../logics/panel/extensionFlagsLogic'
import { extensionPanelLogic } from '../../logics/panel/extensionPanelLogic'
import { ExtensionToolLoading } from '../panel/ExtensionToolLoading'
import { NoPagePosthogBanner } from '../panel/NoPagePosthogBanner'

export function ExtensionFlagsMenu(): JSX.Element {
    const {
        flagsState,
        filteredFlags,
        searchTerm,
        mutationDisabledReason,
        impersonationOpen,
        draftDistinctId,
        draftPayloads,
    } = useValues(extensionFlagsLogic)
    const { projectUrl } = useValues(extensionPanelLogic)
    const {
        setFlagOverride,
        removeFlagOverride,
        openPayloadEditor,
        closePayloadEditor,
        setDraftPayload,
        savePayload,
        setSearchTerm,
        clearOverrides,
        reloadFlags,
        setImpersonationOpen,
        setDraftDistinctId,
        impersonate,
        clearImpersonation,
    } = useActions(extensionFlagsLogic)

    if (!flagsState) {
        return <ExtensionToolLoading />
    }
    const { available, loading, countFlagsOverridden, impersonatedDistinctId, mutationError } = flagsState
    const submitDistinctId = (): void => {
        if (draftDistinctId.trim()) {
            impersonate(draftDistinctId.trim())
        }
    }

    return (
        <div className="flex flex-col gap-2">
            {!available && (
                <NoPagePosthogBanner consequence="the toolbar can't override its flags. The list shows the values PostHog evaluates for you." />
            )}
            {mutationError && (
                <LemonBanner type="error">
                    Couldn't change the flags on this page: {mutationError} Reload the page and try again.
                </LemonBanner>
            )}
            <div className="flex items-center gap-1">
                <LemonInput
                    className="flex-1 min-w-0"
                    type="search"
                    size="small"
                    placeholder="Search flags"
                    value={searchTerm}
                    onChange={setSearchTerm}
                    data-attr="toolbar-extension-flags-search"
                />
                <LemonButton
                    size="small"
                    icon={<IconRefresh />}
                    tooltip="Load the flags again"
                    onClick={reloadFlags}
                    data-attr="toolbar-extension-flags-reload"
                />
                <LemonButton
                    size="small"
                    icon={<IconPerson />}
                    type={impersonatedDistinctId ? 'primary' : 'secondary'}
                    tooltip="See the flags of another person, by distinct ID"
                    disabledReason={available ? null : 'This page has no posthog-js to override'}
                    onClick={() => setImpersonationOpen(!impersonationOpen)}
                    data-attr="toolbar-extension-flags-impersonate"
                />
            </div>
            {impersonatedDistinctId ? (
                <div className="flex items-center gap-2 text-xs">
                    <span className="flex-1 truncate">
                        Viewing as <strong translate="no">{impersonatedDistinctId}</strong>
                    </span>
                    <LemonButton size="xsmall" type="secondary" onClick={clearImpersonation}>
                        Clear
                    </LemonButton>
                </div>
            ) : impersonationOpen ? (
                <div className="flex items-center gap-1">
                    <LemonInput
                        className="flex-1 min-w-0"
                        size="small"
                        placeholder="Distinct ID"
                        value={draftDistinctId}
                        onChange={setDraftDistinctId}
                        onPressEnter={submitDistinctId}
                    />
                    <LemonButton
                        size="small"
                        type="secondary"
                        disabledReason={draftDistinctId.trim() ? null : 'Enter a distinct ID'}
                        onClick={submitDistinctId}
                    >
                        Load
                    </LemonButton>
                </div>
            ) : null}
            {filteredFlags.length > 0 ? (
                <div className="flex flex-col gap-px">
                    {filteredFlags.map((flag) => (
                        <FeatureFlagRow
                            key={flag.key}
                            flag={flag}
                            flagUrl={projectUrl(flag.id ? urls.featureFlag(flag.id) : urls.featureFlags())}
                            payloadDraft={draftPayloads[flag.key] ?? null}
                            payloadError={flagsState.payloadErrors[flag.key] ?? null}
                            disabledReason={mutationDisabledReason}
                            onSetOverride={(value) => setFlagOverride(flag.key, value)}
                            onRemoveOverride={() => removeFlagOverride(flag.key)}
                            onOpenPayloadEditor={(initialDraft) => openPayloadEditor(flag.key, initialDraft)}
                            onPayloadDraftChange={(draft) => setDraftPayload(flag.key, draft)}
                            onSavePayload={() => savePayload(flag.key)}
                            onClosePayloadEditor={() => closePayloadEditor(flag.key)}
                            dataAttrPrefix="toolbar-extension-flag"
                        />
                    ))}
                </div>
            ) : loading ? (
                <ExtensionToolLoading />
            ) : (
                <div className="p-2 text-xs text-secondary">
                    {searchTerm ? 'No flags match your search.' : 'This project has no feature flags.'}
                </div>
            )}
            <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-xs text-secondary">Overrides apply only to this browser.</span>
                <LemonButton
                    size="small"
                    type="secondary"
                    disabledReason={
                        countFlagsOverridden === 0 ? 'No overrides to clear' : (mutationDisabledReason ?? null)
                    }
                    onClick={clearOverrides}
                    data-attr="toolbar-extension-flags-clear-overrides"
                >
                    Clear overrides
                </LemonButton>
            </div>
        </div>
    )
}
