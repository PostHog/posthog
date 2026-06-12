import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { urlToAction } from 'kea-router'

import { SourceConfig, SourceFieldConfig } from '@posthog/query-frontend/schema/schema-general'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { ApiConfig } from '~/lib/api'
import { Breadcrumb } from '~/types'

import { externalDataSourcesStoreCredentialsCreate } from '../../generated/api'
import type { SourceCredentialApi } from '../../generated/api.schemas'
import { availableSourcesLogic } from '../NewSourceScene/availableSourcesLogic'
import { getErrorsForFields } from '../NewSourceScene/sourceWizardLogic'
import type { sourceConnectSceneLogicType } from './sourceConnectSceneLogicType'

const buildCredentialsPayload = async (
    fields: SourceFieldConfig[],
    formPayload: Record<string, any>
): Promise<Record<string, any>> => {
    const payload: Record<string, any> = {}
    for (const field of fields) {
        const value = formPayload[field.name]
        if (field.type === 'file-upload') {
            if (value?.[0]) {
                // Assumes we're loading a JSON file, same as the wizard's submit
                const loadedFile: string = await new Promise((resolve, reject) => {
                    const fileReader = new FileReader()
                    fileReader.onload = (e) => resolve(e.target?.result as string)
                    fileReader.onerror = (e) => reject(e)
                    fileReader.readAsText(value[0])
                })
                payload[field.name] = JSON.parse(loadedFile)
            }
        } else {
            payload[field.name] = value
        }
    }
    return payload
}

export const sourceConnectSceneLogic = kea<sourceConnectSceneLogicType>([
    path(['products', 'dataWarehouse', 'sourceConnectSceneLogic']),
    connect(() => ({
        values: [availableSourcesLogic, ['availableSources', 'availableSourcesLoading']],
    })),
    actions({
        setKind: (kind: string | null) => ({ kind }),
        setStoredCredential: (credential: SourceCredentialApi) => ({ credential }),
    }),
    reducers({
        kind: [
            null as string | null,
            {
                setKind: (_, { kind }) => kind,
            },
        ],
        storedCredential: [
            null as SourceCredentialApi | null,
            {
                setStoredCredential: (_, { credential }) => credential,
            },
        ],
    }),
    selectors({
        sourceConfig: [
            (s) => [s.availableSources, s.kind],
            (availableSources, kind): SourceConfig | null => {
                if (!availableSources || !kind) {
                    return null
                }
                return (
                    Object.values(availableSources).find(
                        (config) => config.name.toLowerCase() === kind.toLowerCase()
                    ) ?? null
                )
            },
        ],
        breadcrumbs: [
            (s) => [s.sourceConfig],
            (sourceConfig): Breadcrumb[] => [
                {
                    key: Scene.Sources,
                    name: 'Sources',
                    path: urls.sources(),
                    iconType: 'data_pipeline',
                },
                {
                    key: Scene.DataWarehouseSourceConnect,
                    name: sourceConfig ? `Connect ${sourceConfig.label ?? sourceConfig.name}` : 'Connect source',
                    iconType: 'data_pipeline',
                },
            ],
        ],
    }),
    forms(({ actions, values }) => ({
        credentialsForm: {
            defaults: { payload: {} } as Record<string, any>,
            errors: (formValues) =>
                getErrorsForFields(values.sourceConfig?.fields ?? [], {
                    prefix: '',
                    payload: (formValues.payload ?? {}) as Record<string, any>,
                }),
            submit: async (formValues) => {
                if (!values.sourceConfig) {
                    return
                }
                let payload: Record<string, any>
                try {
                    payload = await buildCredentialsPayload(
                        values.sourceConfig.fields,
                        (formValues.payload ?? {}) as Record<string, any>
                    )
                } catch {
                    lemonToast.error('File is not valid')
                    return
                }
                const credential = await externalDataSourcesStoreCredentialsCreate(
                    String(ApiConfig.getCurrentTeamId()),
                    { source_type: values.sourceConfig.name, payload }
                )
                actions.setStoredCredential(credential)
            },
        },
    })),
    urlToAction(({ actions }) => ({
        [urls.dataWarehouseSourceConnect()]: (_, searchParams) => {
            actions.setKind(searchParams.kind ?? null)
        },
    })),
])
