import { lemonToast } from '@posthog/lemon-ui'
import { actions, connect, kea, key, listeners, path, props } from 'kea'
import { forms } from 'kea-forms'
import { urlToAction } from 'kea-router'
import api from 'lib/api'

import { ExternalDataSourceCreatePayload, SourceConfig, SourceFieldConfig } from '~/types'

import { getHubspotRedirectUri, sourceWizardLogic } from '../../new/sourceWizardLogic'
import type { sourceFormLogicType } from './sourceFormLogicType'

export interface SourceFormProps {
    sourceConfig: SourceConfig
}

const getErrorsForFields = (
    fields: SourceFieldConfig[]
): ((args: { prefix: string; payload: Record<string, any> }) => Record<string, any>) => {
    return ({ prefix, payload }) => {
        const errors: Record<string, any> = {
            payload: {},
        }

        // Prefix errors
        if (!/^[a-zA-Z0-9_-]*$/.test(prefix)) {
            errors['prefix'] = "Please enter a valid prefix (only letters, numbers, and '_' or '-')."
        }

        // Payload errors
        for (const field of fields) {
            const fieldValue = payload[field.name]
            if (field.required && !fieldValue) {
                errors['payload'][field.name] = `Please enter a ${field.label.toLowerCase()}`
            }
        }

        return errors
    }
}

export const sourceFormLogic = kea<sourceFormLogicType>([
    path(['scenes', 'data-warehouse', 'external', 'sourceFormLogic']),
    key((props) => props.sourceConfig.name),
    props({} as SourceFormProps),
    connect({
        actions: [
            sourceWizardLogic,
            [
                'setDatabaseSchemas',
                'onBack',
                'onNext',
                'selectConnector',
                'loadSources',
                'updateSource',
                'clearSource',
                'setIsLoading',
            ],
        ],
        values: [sourceWizardLogic, ['source']],
    }),
    actions({
        onCancel: true,
        handleRedirect: (kind: string, searchParams: any) => ({ kind, searchParams }),
        getDatabaseSchemas: true,
    }),
    listeners(({ actions, values, props }) => ({
        onCancel: () => {
            actions.clearSource()
            actions.onBack()
            actions.selectConnector(null)
        },
        submitSourceConnectionDetailsSuccess: () => {
            actions.getDatabaseSchemas()
        },
        handleRedirect: async ({ kind, searchParams }) => {
            switch (kind) {
                case 'hubspot': {
                    actions.updateSource({
                        source_type: 'Hubspot',
                        payload: {
                            code: searchParams.code,
                            redirect_uri: getHubspotRedirectUri(),
                        },
                    })
                    return
                }
                default:
                    lemonToast.error(`Something went wrong.`)
            }
        },
        getDatabaseSchemas: async () => {
            const schemas = await api.externalDataSources.database_schema(
                props.sourceConfig.name,
                values.source.payload ?? {}
            )
            actions.setDatabaseSchemas(schemas)
            actions.onNext()
        },
    })),
    urlToAction(({ actions }) => ({
        '/data-warehouse/:kind/redirect': ({ kind = '' }, searchParams) => {
            actions.handleRedirect(kind, searchParams)
        },
    })),
    forms(({ props, actions, values }) => ({
        sourceConnectionDetails: {
            defaults: {
                prefix: values.source?.prefix ?? '',
                source_type: props.sourceConfig.name,
                payload: values.source?.payload ?? {},
            } as ExternalDataSourceCreatePayload,
            errors: getErrorsForFields(props.sourceConfig.fields),
            submit: async (sourceValues) => {
                actions.setIsLoading(true)

                try {
                    await api.externalDataSources.source_prefix(sourceValues.source_type, sourceValues.prefix)
                    actions.updateSource(sourceValues)
                } catch (e: any) {
                    if (e?.data?.message) {
                        actions.setSourceConnectionDetailsManualErrors({ prefix: e.data.message })
                    }
                    actions.setIsLoading(false)

                    throw e
                }
            },
        },
    })),
])
