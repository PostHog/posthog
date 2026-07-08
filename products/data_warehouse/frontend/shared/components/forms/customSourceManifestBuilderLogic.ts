import {
    actions,
    afterMount,
    kea,
    listeners,
    path,
    props,
    propsChanged,
    reducers,
    selectors,
    sharedListeners,
} from 'kea'
import type { FieldName } from 'kea-forms'
import { loaders } from 'kea-loaders'

import { lemonToast } from 'lib/lemon-ui/LemonToast'

import { ApiConfig, ApiError } from '~/lib/api'

import { externalDataSourcesDraftCustomManifestCreate } from 'products/warehouse_sources/frontend/generated/api'
import type { DraftCustomManifestResponseApi } from 'products/warehouse_sources/frontend/generated/api.schemas'

import {
    buildManifest,
    emptyHeader,
    emptyTable,
    extractAuthSecrets,
    type HeaderEntry,
    type ManifestState,
    type Paginator,
    parseManifestIntoState,
    removeTableFromList,
    type TableForm,
    updateTableInList,
} from './customSourceManifest'
import type { customSourceManifestBuilderLogicType } from './customSourceManifestBuilderLogicType'

export interface CustomSourceManifestBuilderLogicProps {
    /** Saved manifest JSON, supplied on the configuration page; undefined in the wizard. */
    initialManifestJson?: string
    /**
     * Writes a value into the outer source form. The mount site differs: the
     * wizard passes `sourceWizardLogic.actions.setSourceConnectionDetailsValue`,
     * the configuration page passes `sourceSettingsLogic.actions.setSourceConfigValue`.
     * Both accept a `(path, value)` signature.
     */
    setValue: (path: FieldName, value: unknown) => void
}

/**
 * Owns the Custom REST source's manifest-builder form state (base URL, auth,
 * headers, tables) and mirrors it into the outer source form as
 * `payload.manifest_json` (the non-secret RESTAPIConfig structure) plus separate
 * `payload.auth_*` secret fields for the credentials.
 *
 * The backend rejoins the two before handing the config to `rest_api_resource()`.
 * Keeping credentials out of the manifest lets the generic API layer redact them
 * with no Custom-source-specific serializer code.
 */
// Intentionally keyless (singleton): the wizard and the configuration tab are
// separate scenes and never mounted at the same time, so kea's mount refcount
// drops to zero between them and `manifestState` / `userHasEdited` reset from
// props on the next mount. If a future caller keeps this logic mounted across
// that transition (e.g. a persistent parent or a second consumer), add a `key()`
// — otherwise the latched `userHasEdited` would make `propsChanged` skip
// re-parsing the new manifest.
export const customSourceManifestBuilderLogic = kea<customSourceManifestBuilderLogicType>([
    props({} as CustomSourceManifestBuilderLogicProps),
    path(['products', 'dataWarehouse', 'customSourceManifestBuilderLogic']),
    actions({
        setManifestState: (state: ManifestState) => ({ state }),
        updateState: (patch: Partial<ManifestState>) => ({ patch }),
        updateTable: (index: number, patch: Partial<TableForm>) => ({ index, patch }),
        updatePaginator: (index: number, paginator: Paginator) => ({ index, paginator }),
        addTable: true,
        removeTable: (index: number) => ({ index }),
        addHeader: true,
        removeHeader: (index: number) => ({ index }),
        updateHeader: (index: number, patch: Partial<HeaderEntry>) => ({ index, patch }),
        // Fires the push listener without changing state — used on mount to mirror the
        // already-parsed initial manifest into the outer form without re-parsing.
        syncToOuterForm: true,
        // UI-only: tracks the generated-manifest <details> disclosure so the
        // CodeSnippet (and its syntax highlighting) only renders while expanded.
        setManifestPreviewOpen: (open: boolean) => ({ open }),
        // AI assist: the docs URL + optional name the user wants to draft a manifest from.
        setDocsUrl: (docsUrl: string) => ({ docsUrl }),
        setSourceName: (sourceName: string) => ({ sourceName }),
        // Switch from the AI intro screen to the full manual builder.
        setShowBuilder: (showBuilder: boolean) => ({ showBuilder }),
    }),
    reducers(({ props }) => ({
        manifestState: [
            parseManifestIntoState(props.initialManifestJson),
            {
                setManifestState: (_, { state }) => state,
                updateState: (state, { patch }) => ({ ...state, ...patch }),
                // Rename/remove cascade to dependent child tables lives in the
                // pure helpers so it stays unit-testable.
                updateTable: (state, { index, patch }) => ({
                    ...state,
                    tables: updateTableInList(state.tables, index, patch),
                }),
                updatePaginator: (state, { index, paginator }) => ({
                    ...state,
                    tables: state.tables.map((table, i) => (i === index ? { ...table, paginator } : table)),
                }),
                addTable: (state) => ({ ...state, tables: [...state.tables, emptyTable()] }),
                removeTable: (state, { index }) => ({
                    ...state,
                    tables: removeTableFromList(state.tables, index),
                }),
                addHeader: (state) => ({ ...state, headers: [...state.headers, emptyHeader()] }),
                removeHeader: (state, { index }) => ({
                    ...state,
                    headers: state.headers.filter((_, i) => i !== index),
                }),
                updateHeader: (state, { index, patch }) => ({
                    ...state,
                    headers: state.headers.map((header, i) => (i === index ? { ...header, ...patch } : header)),
                }),
            },
        ],
        // Gates `pushManifestToOuterForm`: stays false until either an initial
        // manifest arrives or the user edits. Without it the configuration page
        // would clobber the saved manifest with empty defaults on the render
        // between mount and the `job_inputs` poll landing.
        hasContent: [
            Boolean(props.initialManifestJson),
            {
                setManifestState: () => true,
                updateState: () => true,
                updateTable: () => true,
                updatePaginator: () => true,
                addTable: () => true,
                removeTable: () => true,
                addHeader: () => true,
                removeHeader: () => true,
                updateHeader: () => true,
            },
        ],
        // Flips true the moment the user touches any field. Distinct from `hasContent`
        // because we need `propsChanged` to know "was this state edited by the user, or
        // just hydrated from props?" — without it, a late-arriving `job_inputs` poll
        // would silently overwrite in-progress edits.
        userHasEdited: [
            false,
            {
                updateState: () => true,
                updateTable: () => true,
                updatePaginator: () => true,
                addTable: () => true,
                removeTable: () => true,
                addHeader: () => true,
                removeHeader: () => true,
                updateHeader: () => true,
            },
        ],
        manifestPreviewOpen: [
            false,
            {
                setManifestPreviewOpen: (_, { open }) => open,
            },
        ],
        docsUrl: [
            '',
            {
                setDocsUrl: (_, { docsUrl }) => docsUrl,
            },
        ],
        sourceName: [
            '',
            {
                setSourceName: (_, { sourceName }) => sourceName,
            },
        ],
        // The AI intro screen is the default for a fresh source; the configuration page (which passes
        // an initial manifest) and the "Configure manually" button jump straight to the builder.
        showBuilder: [
            Boolean(props.initialManifestJson),
            {
                setShowBuilder: (_, { showBuilder }) => showBuilder,
            },
        ],
    })),
    loaders(({ values }) => ({
        // Drafts a manifest from the docs URL via the backend AI builder. The returned value drives
        // `draftResultLoading` (button spinner); the success listener populates the builder.
        draftResult: [
            null as DraftCustomManifestResponseApi | null,
            {
                generateFromDocs: async (): Promise<DraftCustomManifestResponseApi | null> => {
                    const docsUrl = values.docsUrl.trim()
                    if (!docsUrl) {
                        lemonToast.error('Enter a documentation URL first')
                        return null
                    }
                    return await externalDataSourcesDraftCustomManifestCreate(String(ApiConfig.getCurrentTeamId()), {
                        docs_url: docsUrl,
                        source_name: values.sourceName.trim() || undefined,
                    })
                },
            },
        ],
    })),
    selectors({
        manifestJson: [(s) => [s.manifestState], (state): string => JSON.stringify(buildManifest(state), null, 2)],
        authSecrets: [(s) => [s.manifestState], (state) => extractAuthSecrets(state)],
    }),
    sharedListeners(({ values, props }) => ({
        pushManifestToOuterForm: () => {
            if (!values.hasContent) {
                return
            }
            props.setValue(['payload', 'manifest_json'] as FieldName, values.manifestJson)
            // Secrets go to their own fields so the backend redacts them generically;
            // the manifest itself stays non-secret and round-trips to the config tab.
            // Field names must match the backend SourceFieldInputConfig names exactly.
            props.setValue(['payload', 'auth_token'] as FieldName, values.authSecrets.auth_token)
            props.setValue(['payload', 'auth_api_key'] as FieldName, values.authSecrets.auth_api_key)
            props.setValue(['payload', 'auth_password'] as FieldName, values.authSecrets.auth_password)
            props.setValue(
                ['payload', 'auth_oauth2_client_secret'] as FieldName,
                values.authSecrets.auth_oauth2_client_secret
            )
            props.setValue(
                ['payload', 'auth_oauth2_refresh_token'] as FieldName,
                values.authSecrets.auth_oauth2_refresh_token
            )
        },
    })),
    // Every state mutation re-pushes the serialized manifest + secrets to the
    // outer form — this replaces the effect that watched the derived values.
    listeners(({ sharedListeners, actions }) => ({
        setManifestState: sharedListeners.pushManifestToOuterForm,
        updateState: sharedListeners.pushManifestToOuterForm,
        updateTable: sharedListeners.pushManifestToOuterForm,
        updatePaginator: sharedListeners.pushManifestToOuterForm,
        addTable: sharedListeners.pushManifestToOuterForm,
        removeTable: sharedListeners.pushManifestToOuterForm,
        addHeader: sharedListeners.pushManifestToOuterForm,
        removeHeader: sharedListeners.pushManifestToOuterForm,
        updateHeader: sharedListeners.pushManifestToOuterForm,
        syncToOuterForm: sharedListeners.pushManifestToOuterForm,
        generateFromDocsSuccess: ({ draftResult }) => {
            if (!draftResult) {
                return
            }
            // Populate the builder from the draft so the user reviews and adds credentials before
            // creating; secrets are never in the manifest, so the auth_* fields stay for them to fill.
            if (draftResult.manifest_json) {
                actions.setManifestState(parseManifestIntoState(draftResult.manifest_json))
                // Move to the builder so the user reviews the draft and fills in credentials.
                actions.setShowBuilder(true)
            }
            if (draftResult.draft_status === 'ok') {
                lemonToast.success(
                    `Drafted a manifest with ${draftResult.resource_names.length} table(s). Review it and add your credentials.`
                )
            } else {
                lemonToast.warning(
                    draftResult.error || 'Could not fully validate the manifest — review and fix it before creating.'
                )
            }
        },
        generateFromDocsFailure: ({ errorObject }) => {
            // Surface the backend's specific reason instead of a blanket message: 4xx/5xx bodies carry
            // `data.message`, while a 429 throttle carries DRF's `data.detail` ("…available in N
            // seconds") — telling a rate-limited user to "try again" immediately would be wrong.
            const apiError = errorObject instanceof ApiError ? errorObject : undefined
            const message = apiError?.data?.message || apiError?.data?.detail
            lemonToast.error(message || 'Failed to draft a manifest. Try again, or configure it manually.')
        },
    })),
    afterMount(({ actions, props }) => {
        // The reducer already parsed `initialManifestJson` at mount, but the listeners
        // that push to the outer form only fire on actions. Dispatch a no-op sync so
        // the configuration page reflects the saved manifest even before the user edits.
        // The wizard mounts with no manifest — a no-op there.
        if (props.initialManifestJson) {
            actions.syncToOuterForm()
        }
    }),
    propsChanged(({ actions, values, props }, oldProps) => {
        // The configuration page loads `source.job_inputs` via a poll, so the
        // manifest typically arrives a beat after mount. Re-parse on a real value
        // change — but only when the user hasn't started editing yet, so a
        // late-arriving poll doesn't wipe in-progress edits.
        if (
            !values.userHasEdited &&
            props.initialManifestJson !== oldProps.initialManifestJson &&
            props.initialManifestJson
        ) {
            actions.setManifestState(parseManifestIntoState(props.initialManifestJson))
            // An existing source's manifest arrived (often a beat after mount, via the config-page
            // poll): it already has a manifest, so open straight in the builder, never the AI intro.
            actions.setShowBuilder(true)
        }
    }),
])
