import Fuse from 'fuse.js'
import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { encodeParams } from 'kea-router'
import type { PostHog } from 'posthog-js'

import { permanentlyMount } from 'lib/utils/kea-logic-builders'

import { toolbarConfigLogic, toolbarFetch } from '~/toolbar/toolbarConfigLogic'
import { toolbarPosthogJS } from '~/toolbar/toolbarPosthogJS'
import { CombinedFeatureFlagAndValueType } from '~/types'

import type { flagsToolbarLogicType } from './flagsToolbarLogicType'

export type PayloadOverrides = Record<string, any>

export const flagsToolbarLogic = kea<flagsToolbarLogicType>([
    path(['toolbar', 'flags', 'flagsToolbarLogic']),
    connect(() => ({
        values: [toolbarConfigLogic, ['posthog']],
        actions: [toolbarConfigLogic, ['logout', 'tokenExpired']],
    })),
    actions({
        getUserFlags: true,
        setFeatureFlagValueFromPostHogClient: (flags: string[], variants: Record<string, string | boolean>) => ({
            flags,
            variants,
        }),
        setOverriddenUserFlag: (
            flagKey: string,
            overrideValue: string | boolean,
            payloadOverride?: PayloadOverrides
        ) => ({
            flagKey,
            overrideValue,
            payloadOverride,
        }),
        setPayloadOverride: (flagKey: string, payload: any) => ({ flagKey, payload }),
        deleteOverriddenUserFlag: (flagKey: string) => ({ flagKey }),
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        checkLocalOverrides: true,
        storeLocalOverrides: (localOverrides: Record<string, string | boolean>) => ({ localOverrides }),
        setDraftPayload: (flagKey: string, draftPayload: string) => ({ flagKey, draftPayload }),
        savePayloadOverride: (flagKey: string) => ({ flagKey }),
        setPayloadError: (flagKey: string, error: string | null) => ({ flagKey, error }),
        setPayloadEditorOpen: (flagKey: string, isOpen: boolean) => ({ flagKey, isOpen }),
    }),
    loaders(({ values }) => ({
        userFlags: [
            [] as CombinedFeatureFlagAndValueType[],
            {
                getUserFlags: async (_, breakpoint) => {
                    const params = {
                        groups: getGroups(values.posthog),
                    }
                    const response = await toolbarFetch(
                        `/api/projects/@current/feature_flags/my_flags${encodeParams(params, '?')}`
                    )

                    breakpoint()
                    if (!response.ok) {
                        return []
                    }
                    return await response.json()
                },
            },
        ],
    })),
    reducers({
        localOverrides: [
            {} as Record<string, string | boolean>,
            {
                storeLocalOverrides: (_, { localOverrides }) => localOverrides,
            },
        ],
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
            },
        ],
        posthogClientFlagValues: [
            {} as Record<string, string | boolean>,
            {
                setFeatureFlagValueFromPostHogClient: (_, { variants }) => {
                    return variants
                },
            },
        ],
        payloadOverrides: [
            {} as PayloadOverrides,
            {
                setPayloadOverride: (state, { flagKey, payload }) => ({
                    ...state,
                    [flagKey]: payload,
                }),
                deleteOverriddenUserFlag: (state, { flagKey }) => {
                    const newState = { ...state }
                    delete newState[flagKey]
                    return newState
                },
            },
        ],
        draftPayloads: [
            {} as Record<string, string>,
            {
                setDraftPayload: (state, { flagKey, draftPayload }) => ({
                    ...state,
                    [flagKey]: draftPayload,
                }),
                deleteOverriddenUserFlag: (state, { flagKey }) => {
                    const newState = { ...state }
                    delete newState[flagKey]
                    return newState
                },
            },
        ],
        payloadErrors: [
            {} as Record<string, string | null>,
            {
                setPayloadError: (state, { flagKey, error }) => ({
                    ...state,
                    [flagKey]: error,
                }),
                setDraftPayload: (state, { flagKey }) => ({
                    ...state,
                    [flagKey]: null,
                }),
            },
        ],
        openPayloadEditors: [
            {} as Record<string, boolean>,
            {
                setPayloadEditorOpen: (state, { flagKey, isOpen }) => ({
                    ...state,
                    [flagKey]: isOpen,
                }),
                deleteOverriddenUserFlag: (state, { flagKey }) => {
                    const newState = { ...state }
                    delete newState[flagKey]
                    return newState
                },
            },
        ],
    }),
    selectors({
        userFlagsWithOverrideInfo: [
            (s) => [s.userFlags, s.localOverrides, s.posthogClientFlagValues, s.payloadOverrides],
            (userFlags, localOverrides, posthogClientFlagValues, payloadOverrides) => {
                return userFlags.map((flag) => {
                    const hasVariants = (flag.feature_flag.filters?.multivariate?.variants?.length || 0) > 0

                    const currentValue =
                        flag.feature_flag.key in localOverrides
                            ? localOverrides[flag.feature_flag.key]
                            : (posthogClientFlagValues[flag.feature_flag.key] ?? flag.value)

                    return {
                        ...flag,
                        hasVariants,
                        currentValue,
                        hasOverride: flag.feature_flag.key in localOverrides,
                        payloadOverride: payloadOverrides[flag.feature_flag.key],
                    }
                })
            },
        ],
        filteredFlags: [
            (s) => [s.searchTerm, s.userFlagsWithOverrideInfo],
            (searchTerm, userFlagsWithOverrideInfo) => {
                return searchTerm
                    ? new Fuse(userFlagsWithOverrideInfo, {
                          threshold: 0.3,
                          keys: ['feature_flag.key', 'feature_flag.name'],
                      })
                          .search(searchTerm)
                          .map(({ item }) => item)
                    : userFlagsWithOverrideInfo
            },
        ],
        countFlagsOverridden: [(s) => [s.localOverrides], (localOverrides) => Object.keys(localOverrides).length],
    }),
    listeners(({ actions, values }) => {
        const clearFeatureFlagOverrides = (): void => {
            const clientPostHog = values.posthog
            if (clientPostHog) {
                clientPostHog.featureFlags.overrideFeatureFlags(false)
                clientPostHog.featureFlags.reloadFeatureFlags()
                actions.storeLocalOverrides({})
            }
        }

        return {
            checkLocalOverrides: () => {
                const clientPostHog = values.posthog
                if (clientPostHog) {
                    const locallyOverrideFeatureFlags = clientPostHog.get_property('$override_feature_flags') || {}
                    actions.storeLocalOverrides(locallyOverrideFeatureFlags)
                }
            },
            setOverriddenUserFlag: ({ flagKey, overrideValue, payloadOverride }) => {
                const clientPostHog = values.posthog
                if (clientPostHog) {
                    const payloads = payloadOverride ? { [flagKey]: payloadOverride } : undefined
                    clientPostHog.featureFlags.overrideFeatureFlags({
                        flags: { ...values.localOverrides, [flagKey]: overrideValue },
                        payloads: payloads,
                    })
                    toolbarPosthogJS.capture('toolbar feature flag overridden')
                    actions.checkLocalOverrides()
                    if (payloadOverride) {
                        actions.setPayloadOverride(flagKey, payloadOverride)
                    }
                    clientPostHog.featureFlags.reloadFeatureFlags()
                }
            },
            deleteOverriddenUserFlag: ({ flagKey }) => {
                const clientPostHog = values.posthog
                if (clientPostHog) {
                    const updatedFlags = { ...values.localOverrides }
                    delete updatedFlags[flagKey]
                    if (Object.keys(updatedFlags).length > 0) {
                        clientPostHog.featureFlags.overrideFeatureFlags({ flags: updatedFlags })
                    } else {
                        clientPostHog.featureFlags.overrideFeatureFlags(false)
                    }
                    toolbarPosthogJS.capture('toolbar feature flag override removed')
                    actions.checkLocalOverrides()
                    clientPostHog.featureFlags.reloadFeatureFlags()
                }
            },
            savePayloadOverride: ({ flagKey }) => {
                try {
                    const draftPayload = values.draftPayloads[flagKey]
                    if (!draftPayload || draftPayload.trim() === '') {
                        actions.setPayloadError(flagKey, null)
                        actions.setPayloadOverride(flagKey, null)
                        actions.setOverriddenUserFlag(flagKey, true)
                        actions.setPayloadEditorOpen(flagKey, false)
                        return
                    }

                    const payload = JSON.parse(draftPayload)
                    actions.setPayloadError(flagKey, null)
                    actions.setOverriddenUserFlag(flagKey, true, payload)
                    actions.setPayloadEditorOpen(flagKey, false)
                } catch (e) {
                    actions.setPayloadError(flagKey, 'Invalid JSON')
                    console.error('Invalid JSON:', e)
                }
            },
            logout: () => {
                clearFeatureFlagOverrides()
            },
            tokenExpired: () => {
                clearFeatureFlagOverrides()
            },
        }
    }),
    permanentlyMount(),
])

function getGroups(posthogInstance: PostHog | null): Record<string, any> {
    try {
        return posthogInstance?.getGroups() || {}
    } catch {
        return {}
    }
}
