import { actions, connect, kea, key, listeners, path, props } from 'kea'
import { forms } from 'kea-forms'
import api from 'lib/api'

import { ExternalDataSourceCreatePayload, SourceConfig, SourceFieldConfig } from '~/types'

import { sourceWizardLogic } from '../../new/sourceWizardLogic'
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
        getDatabaseSchemas: async () => {
            const schemas = await api.externalDataSources.database_schema(
                props.sourceConfig.name,
                values.source.payload ?? {}
            )
            actions.setDatabaseSchemas(schemas)
            actions.onNext()
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
