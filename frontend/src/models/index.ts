import { kea } from 'kea'
import { actionsModel } from './actionsModel'
import { annotationsModel } from './annotationsModel'
import { cohortsModel } from './cohortsModel'
import { dashboardsModel } from './dashboardsModel'
import { eventDefinitionsLogic } from './eventDefinitionsLogic'
import { propertyDefinitionsLogic } from './propertyDefinitionsLogic'

import { modelsType } from './indexType'

/** "Models" are logics that are persistently mounted (start with app) */
export const models = kea<modelsType>({
    connect: [
        actionsModel,
        annotationsModel,
        cohortsModel,
        dashboardsModel,
        eventDefinitionsLogic,
        propertyDefinitionsLogic,
    ],
})
