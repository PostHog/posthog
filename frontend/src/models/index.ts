import { kea } from 'kea'
import { actionsModel } from './actionsModel'
import { annotationsModel } from './annotationsModel'
import { cohortsModel } from './cohortsModel'
import { dashboardsModel } from './dashboardsModel'
import { eventDefinitionsModel } from './eventDefinitionsModel'
import { personPropertiesModel } from './personPropertiesModel'
import { propertyDefinitionsModel } from './propertyDefinitionsModel'

import { modelsType } from './indexType'
import { getProjectBasedLogicKeyBuilder, ProjectBasedLogicProps } from 'lib/utils/logics'

/** "Models" are logics that are persistently mounted (start with app) */
export const models = kea<modelsType>({
    props: {} as ProjectBasedLogicProps,
    key: getProjectBasedLogicKeyBuilder(),
    connect: (props: ProjectBasedLogicProps) => [
        actionsModel({ teamId: props.teamId }),
        annotationsModel({ teamId: props.teamId }),
        cohortsModel,
        dashboardsModel,
        eventDefinitionsModel,
        personPropertiesModel,
        propertyDefinitionsModel,
    ],
})
