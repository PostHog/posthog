import { kea, key, path, props } from 'kea'
import { forms } from 'kea-forms'

import { isNumber } from 'lib/utils'
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
    return Object.keys(props.migration.parameter_definitions).reduce<Record<string, number>>((acc, key) => {
        const parameter = props.migration.parameters[key]
        const parameterDefinition = props.migration.parameter_definitions[key][0]
        if (parameter) {
            acc[key] = parameter
        } else if (isNumber(parameterDefinition)) {
            acc[key] = parameterDefinition
        }
        return acc
    }, {})
}
