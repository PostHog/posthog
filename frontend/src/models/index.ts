import { kea } from 'kea'
import { actionsModel } from './actionsModel'
import { annotationsModel } from './annotationsModel'
import { cohortsModel } from './cohortsModel'
import { dashboardsModel } from './dashboardsModel'
import { eventDefinitionsModel } from './eventDefinitionsModel'
import { personPropertiesModel } from './personPropertiesModel'
import { propertyDefinitionsModel } from './propertyDefinitionsModel'

import type { modelsType } from './indexType'

/** "Models" are logics that are persistently mounted (start with app) */
export const models = kea<modelsType>({
    path: ['models', 'index'],
    connect: [
        actionsModel,
        annotationsModel,
        cohortsModel,
        dashboardsModel,
        eventDefinitionsModel,
        personPropertiesModel,
        propertyDefinitionsModel,
    ],
})
