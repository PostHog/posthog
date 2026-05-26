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

import {
    buildManifest,
    emptyStream,
    extractAuthSecrets,
    type HeaderEntry,
    type ManifestState,
    type Paginator,
    parseManifestIntoState,
    type StreamForm,
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
 * headers, streams) and mirrors it into the outer source form as
 * `payload.manifest_json` (the non-secret RESTAPIConfig structure) plus separate
 * `payload.auth_*` secret fields for the credentials.
 *
 * The backend rejoins the two before handing the config to `rest_api_resource()`.
 * Keeping credentials out of the manifest lets the generic API layer redact them
 * with no Custom-source-specific serializer code.
 */
export const customSourceManifestBuilderLogic = kea<customSourceManifestBuilderLogicType>([
    props({} as CustomSourceManifestBuilderLogicProps),
    path(['products', 'dataWarehouse', 'customSourceManifestBuilderLogic']),
    actions({
        setManifestState: (state: ManifestState) => ({ state }),
        updateState: (patch: Partial<ManifestState>) => ({ patch }),
        updateStream: (index: number, patch: Partial<StreamForm>) => ({ index, patch }),
        updatePaginator: (index: number, paginator: Paginator) => ({ index, paginator }),
        addStream: true,
        removeStream: (index: number) => ({ index }),
        addHeader: true,
        removeHeader: (index: number) => ({ index }),
        updateHeader: (index: number, patch: Partial<HeaderEntry>) => ({ index, patch }),
        // Fires the push listener without changing state — used on mount to mirror the
        // already-parsed initial manifest into the outer form without re-parsing.
        syncToOuterForm: true,
    }),
    reducers(({ props }) => ({
        manifestState: [
            parseManifestIntoState(props.initialManifestJson),
            {
                setManifestState: (_, { state }) => state,
                updateState: (state, { patch }) => ({ ...state, ...patch }),
                updateStream: (state, { index, patch }) => ({
                    ...state,
                    streams: state.streams.map((stream, i) => (i === index ? { ...stream, ...patch } : stream)),
                }),
                updatePaginator: (state, { index, paginator }) => ({
                    ...state,
                    streams: state.streams.map((stream, i) => (i === index ? { ...stream, paginator } : stream)),
                }),
                addStream: (state) => ({ ...state, streams: [...state.streams, emptyStream()] }),
                removeStream: (state, { index }) => ({
                    ...state,
                    streams: state.streams.filter((_, i) => i !== index),
                }),
                addHeader: (state) => ({ ...state, headers: [...state.headers, { key: '', value: '' }] }),
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
                updateStream: () => true,
                updatePaginator: () => true,
                addStream: () => true,
                removeStream: () => true,
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
                updateStream: () => true,
                updatePaginator: () => true,
                addStream: () => true,
                removeStream: () => true,
                addHeader: () => true,
                removeHeader: () => true,
                updateHeader: () => true,
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
            props.setValue(['payload', 'auth_token'] as FieldName, values.authSecrets.auth_token)
            props.setValue(['payload', 'auth_api_key'] as FieldName, values.authSecrets.auth_api_key)
            props.setValue(['payload', 'auth_password'] as FieldName, values.authSecrets.auth_password)
        },
    })),
    // Every state mutation re-pushes the serialized manifest + secrets to the
    // outer form — this replaces the effect that watched the derived values.
    listeners(({ sharedListeners }) => ({
        setManifestState: sharedListeners.pushManifestToOuterForm,
        updateState: sharedListeners.pushManifestToOuterForm,
        updateStream: sharedListeners.pushManifestToOuterForm,
        updatePaginator: sharedListeners.pushManifestToOuterForm,
        addStream: sharedListeners.pushManifestToOuterForm,
        removeStream: sharedListeners.pushManifestToOuterForm,
        addHeader: sharedListeners.pushManifestToOuterForm,
        removeHeader: sharedListeners.pushManifestToOuterForm,
        updateHeader: sharedListeners.pushManifestToOuterForm,
        syncToOuterForm: sharedListeners.pushManifestToOuterForm,
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
        }
    }),
])
