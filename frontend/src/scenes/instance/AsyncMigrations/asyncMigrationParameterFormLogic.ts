import { kea, key, props, path } from 'kea'
import { forms } from 'kea-forms'
import { AsyncMigrationModalProps, asyncMigrationsLogic } from 'scenes/instance/AsyncMigrations/asyncMigrationsLogic'

import type { asyncMigrationParameterFormLogicType } from './asyncMigrationParameterFormLogicType'

export const asyncMigrationParameterFormLogic = kea<asyncMigrationParameterFormLogicType>([
    path(['scenes', 'instance', 'AsyncMigrations', 'asyncMigrationParameterFormLogic']),
    props({} as AsyncMigrationModalProps),
    key((props) => props.migration.id),

    forms(({ props }) => ({
        parameters: {
            defaults: defaultParameters(props),

            submit: async (parameters: Record<string, number>) => {
                asyncMigrationsLogic.actions.updateMigrationStatus(
                    {
                        ...props.migration,
                        parameters,
                    },
                    props.endpoint,
                    props.message
                )
            },
        },
    })),
])

function defaultParameters(props: AsyncMigrationModalProps): Record<string, number> {
    const result = {}
    Object.keys(props.migration.parameter_definitions).forEach((key) => {
        if (props.migration.parameters[key]) {
            result[key] = props.migration.parameters[key]
        } else {
            result[key] = props.migration.parameter_definitions[key][0]
        }
    })
    return result
}
