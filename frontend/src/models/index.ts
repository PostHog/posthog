import { kea } from 'kea'
import { actionsModel } from './actionsModel'
import { annotationsModel } from './annotationsModel'
import { cohortsModel } from './cohortsModel'
import { dashboardsModel } from './dashboardsModel'
import { eventDefinitionsModel } from './eventDefinitionsModel'
import { personPropertiesModel } from './personPropertiesModel'
import { propertyDefinitionsModel } from './propertyDefinitionsModel'

import { modelsType } from './indexType'
import { ProjectBasedLogicProps } from '../types'

/** "Models" are project-based logics that are mounted as soon as the current project is loaded. */
export const models = kea<modelsType>({
    props: {} as ProjectBasedLogicProps,
    key: (props) => props.teamId || '',
    connect: ({ teamId }: ProjectBasedLogicProps) =>
        teamId
            ? [
                  actionsModel({ teamId }),
                  annotationsModel({ teamId }),
                  cohortsModel({ teamId }),
                  dashboardsModel({ teamId }),
                  eventDefinitionsModel({ teamId }),
                  personPropertiesModel({ teamId }),
                  propertyDefinitionsModel({ teamId }),
              ]
            : [],
})
