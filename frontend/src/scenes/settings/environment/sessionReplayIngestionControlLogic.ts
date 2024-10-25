import { actions, afterMount, connect, kea, listeners, path, props, reducers, selectors, sharedListeners } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { subscriptions } from 'kea-subscriptions'
import api from 'lib/api'
import { isObject } from 'lib/utils'
import { variantKeyToIndexFeatureFlagPayloads } from 'scenes/feature-flags/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { FeatureFlagBasicType, SessionReplayUrlTriggerConfig, TeamPublicType, TeamType } from '~/types'

import type { sessionReplayIngestionControlLogicType } from './sessionReplayIngestionControlLogicType'

const NEW_URL_TRIGGER = { url: '', matching: 'regex' }

export const sessionReplayIngestionControlLogic = kea<sessionReplayIngestionControlLogicType>([
    path(['scenes', 'settings', 'project', 'sessionReplayIngestionControlLogic']),
    actions({
        selectFeatureFlag: (flag: FeatureFlagBasicType) => ({ flag }),

        setUrlTriggerConfig: (urlTriggerConfig: SessionReplayUrlTriggerConfig[]) => ({ urlTriggerConfig }),
        addUrlTrigger: (urlTriggerConfig: SessionReplayUrlTriggerConfig) => ({ urlTriggerConfig }),
        removeUrlTrigger: (index: number) => ({ index }),
        updateUrlTrigger: (index: number, urlTriggerConfig: SessionReplayUrlTriggerConfig) => ({
            index,
            urlTriggerConfig,
        }),
        setEditUrlTriggerIndex: (originalIndex: number | null) => ({ originalIndex }),
        newUrlTrigger: true,
        cancelProposingUrlTrigger: true,

        setUrlBlocklistConfig: (urlBlocklistConfig: SessionReplayUrlTriggerConfig[]) => ({ urlBlocklistConfig }),
        addUrlBlocklist: (urlBlocklistConfig: SessionReplayUrlTriggerConfig) => ({ urlBlocklistConfig }),
        removeUrlBlocklist: (index: number) => ({ index }),
        updateUrlBlocklist: (index: number, urlBlocklistConfig: SessionReplayUrlTriggerConfig) => ({
            index,
            urlBlocklistConfig,
        }),
        setEditUrlBlocklistIndex: (originalIndex: number | null) => ({ originalIndex }),
        newUrlBlocklist: true,
        cancelProposingUrlBlocklist: true,
    }),
    connect({ values: [teamLogic, ['currentTeam']], actions: [teamLogic, ['updateCurrentTeam']] }),
    reducers({
        selectedFlag: [
            null as FeatureFlagBasicType | null,
            {
                selectFeatureFlag: (_, { flag }) => flag,
            },
        ],
        urlTriggerConfig: [
            null as SessionReplayUrlTriggerConfig[] | null,
            {
                setUrlTriggerConfig: (_, { urlTriggerConfig }) => urlTriggerConfig,
                addUrlTrigger: (state, { urlTriggerConfig }) => [...(state ?? []), urlTriggerConfig],
                updateUrlTrigger: (state, { index, urlTriggerConfig: newUrlTriggerConfig }) =>
                    (state ?? []).map((triggerConfig, i) => (i === index ? newUrlTriggerConfig : triggerConfig)),
                removeUrlTrigger: (state, { index }) => {
                    return (state ?? []).filter((_, i) => i !== index)
                },
            },
        ],
        editUrlTriggerIndex: [
            null as number | null,
            {
                setEditUrlTriggerIndex: (_, { originalIndex }) => originalIndex,
                removeUrlTrigger: (editUrlTriggerIndex, { index }) =>
                    editUrlTriggerIndex && index < editUrlTriggerIndex
                        ? editUrlTriggerIndex - 1
                        : index === editUrlTriggerIndex
                        ? null
                        : editUrlTriggerIndex,
                newUrlTrigger: () => -1,
                updateUrlTrigger: () => null,
                addUrlTrigger: () => null,
                cancelProposingUrlTrigger: () => null,
            },
        ],
        urlBlocklistConfig: [
            null as SessionReplayUrlTriggerConfig[] | null,
            {
                setUrlBlocklistConfig: (_, { urlBlocklistConfig }) => urlBlocklistConfig,
            },
        ],
        editUrlBlocklistIndex: [
            null as number | null,
            {
                setEditUrlBlocklistIndex: (_, { originalIndex }) => originalIndex,
                removeUrlBlocklist: (editUrlBlocklistIndex, { index }) =>
                    editUrlBlocklistIndex && index < editUrlBlocklistIndex
                        ? editUrlBlocklistIndex - 1
                        : index === editUrlBlocklistIndex
                        ? null
                        : editUrlBlocklistIndex,
                newUrlBlocklist: () => -1,
                updateUrlBlocklist: () => null,
                addUrlBlocklist: () => null,
            },
        ],
    }),
    props({}),
    loaders(({ values }) => ({
        featureFlag: {
            loadFeatureFlag: async () => {
                if (values.linkedFeatureFlagId) {
                    const retrievedFlag = await api.featureFlags.get(values.linkedFeatureFlagId)
                    return variantKeyToIndexFeatureFlagPayloads(retrievedFlag)
                }
                return null
            },
        },
    })),
    selectors({
        linkedFeatureFlagId: [
            (s) => [s.currentTeam],
            (currentTeam) => currentTeam?.session_recording_linked_flag?.id || null,
        ],
        linkedFlag: [
            (s) => [s.featureFlag, s.selectedFlag, s.currentTeam],
            // an existing linked flag is loaded from the API,
            // a newly chosen flag is selected can be passed in
            // the current team is used to ensure that we don't show stale values
            // as people change the selection
            (featureFlag, selectedFlag, currentTeam) =>
                currentTeam?.session_recording_linked_flag?.id ? selectedFlag || featureFlag : null,
        ],
        flagHasVariants: [(s) => [s.linkedFlag], (linkedFlag) => isObject(linkedFlag?.filters.multivariate)],

        remoteUrlTriggerConfig: [
            (s) => [s.currentTeam],
            (currentTeam) => currentTeam?.session_recording_url_trigger_config,
        ],
        isAddUrlTriggerConfigFormVisible: [
            (s) => [s.editUrlTriggerIndex],
            (editUrlTriggerIndex) => editUrlTriggerIndex === -1,
        ],
        urlTriggerToEdit: [
            (s) => [s.urlTriggerConfig, s.editUrlTriggerIndex],
            (urlTriggerConfig, editUrlTriggerIndex) => {
                if (
                    editUrlTriggerIndex === null ||
                    editUrlTriggerIndex === -1 ||
                    !urlTriggerConfig?.[editUrlTriggerIndex]
                ) {
                    return NEW_URL_TRIGGER
                }
                return urlTriggerConfig[editUrlTriggerIndex]
            },
        ],

        remoteUrlBlocklistConfig: [
            (s) => [s.currentTeam],
            (currentTeam) => currentTeam?.session_recording_url_blocklist_config,
        ],
        isAddUrlBlocklistConfigFormVisible: [
            (s) => [s.editUrlBlocklistIndex],
            (editUrlBlocklistIndex) => editUrlBlocklistIndex === -1,
        ],
        urlBlocklistToEdit: [
            (s) => [s.urlBlocklistConfig, s.editUrlBlocklistIndex],
            (urlBlocklistConfig, editUrlBlocklistIndex) => {
                if (
                    editUrlBlocklistIndex === null ||
                    editUrlBlocklistIndex === -1 ||
                    !urlBlocklistConfig?.[editUrlBlocklistIndex]
                ) {
                    return NEW_URL_TRIGGER
                }
                return urlBlocklistConfig[editUrlBlocklistIndex]
            },
        ],
    }),
    afterMount(({ actions }) => {
        actions.loadFeatureFlag()
    }),
    subscriptions(({ actions }) => ({
        currentTeam: (currentTeam: TeamPublicType | TeamType | null) => {
            actions.setUrlTriggerConfig(currentTeam?.session_recording_url_trigger_config ?? [])
            actions.setUrlBlocklistConfig(currentTeam?.session_recording_url_blocklist_config ?? [])
        },
    })),
    forms(({ values, actions }) => ({
        proposedUrlTrigger: {
            defaults: { url: '', matching: 'regex' } as SessionReplayUrlTriggerConfig,
            submit: async ({ url, matching }) => {
                if (values.editUrlTriggerIndex !== null && values.editUrlTriggerIndex >= 0) {
                    actions.updateUrlTrigger(values.editUrlTriggerIndex, { url, matching })
                } else {
                    actions.addUrlTrigger({ url, matching })
                }
            },
        },
        proposedUrlBlocklist: {
            defaults: { url: '', matching: 'regex' } as SessionReplayUrlTriggerConfig,
            submit: async ({ url, matching }) => {
                if (values.editUrlBlocklistIndex !== null && values.editUrlBlocklistIndex >= 0) {
                    actions.updateUrlBlocklist(values.editUrlBlocklistIndex, { url, matching })
                } else {
                    actions.addUrlBlocklist({ url, matching })
                }
            },
        },
    })),
    sharedListeners(({ values }) => ({
        saveUrlTriggers: async () => {
            await teamLogic.asyncActions.updateCurrentTeam({
                session_recording_url_trigger_config: values.urlTriggerConfig ?? [],
            })
        },
        saveUrlBlocklists: async () => {
            await teamLogic.asyncActions.updateCurrentTeam({
                session_recording_url_blocklist_config: values.urlBlocklistConfig ?? [],
            })
        },
    })),
    listeners(({ sharedListeners, actions, values }) => ({
        setEditUrlTriggerIndex: () => {
            actions.setProposedUrlTriggerValue('url', values.urlTriggerToEdit.url)
            actions.setProposedUrlTriggerValue('matching', values.urlTriggerToEdit.matching)
        },
        addUrlTrigger: sharedListeners.saveUrlTriggers,
        removeUrlTrigger: sharedListeners.saveUrlTriggers,
        updateUrlTrigger: sharedListeners.saveUrlTriggers,
        submitProposedUrlTriggerSuccess: () => {
            actions.setEditUrlTriggerIndex(null)
            actions.resetProposedUrlTrigger()
        },

        setEditUrlBlocklistIndex: () => {
            actions.setProposedUrlBlocklistValue('url', values.urlBlocklistToEdit.url)
            actions.setProposedUrlBlocklistValue('matching', values.urlBlocklistToEdit.matching)
        },
        addUrlBlocklist: sharedListeners.saveUrlBlocklists,
        removeUrlBlocklist: sharedListeners.saveUrlBlocklists,
        updateUrlBlocklist: sharedListeners.saveUrlBlocklists,
        submitProposedUrlBlocklistSuccess: () => {
            actions.setEditUrlBlocklistIndex(null)
            actions.resetProposedUrlBlocklist()
        },
    })),
])
