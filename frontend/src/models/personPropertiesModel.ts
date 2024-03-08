import { connect, events, kea, key, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { combineUrl } from 'kea-router'
import api from 'lib/api'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { dataWarehouseJoinsLogic } from 'scenes/data-warehouse/external/dataWarehouseJoinsLogic'
import { teamLogic } from 'scenes/teamLogic'

import { PersonProperty } from '~/types'

import type { personPropertiesModelType } from './personPropertiesModelType'
import { PersonPropertiesModelProps } from './types'

export const personPropertiesModel = kea<personPropertiesModelType>([
    props({} as PersonPropertiesModelProps),
    path(['models', 'personPropertiesModel']),
    key((props) => props.taxonomicFilterLogicKey),
    connect({
        values: [
            teamLogic,
            ['currentTeamId'],
            dataWarehouseJoinsLogic,
            ['columnsJoinedToPersons'],
            featureFlagLogic,
            ['featureFlags'],
        ],
    }),
    loaders(({ values }) => ({
        personProperties: [
            [] as PersonProperty[],
            {
                loadPersonProperties: async () => {
                    const url = combineUrl(`api/projects/${values.currentTeamId}/property_definitions`, {
                        type: 'person',
                        properties: values.propertyAllowList?.[TaxonomicFilterGroupType.PersonProperties]
                            ? values.propertyAllowList[TaxonomicFilterGroupType.PersonProperties].join(',')
                            : undefined,
                    }).url
                    return (await api.get(url)).results
                },
            },
        ],
    })),
    selectors(() => ({
        combinedPersonProperties: [
            (s) => [s.personProperties, s.columnsJoinedToPersons, s.featureFlags],
            (personProperties, columnsJoinedToPersons, featureFlags) => {
                if (featureFlags[FEATURE_FLAGS.DATA_WAREHOUSE]) {
                    return [...personProperties, ...columnsJoinedToPersons]
                }
                return [...personProperties]
            },
        ],
        propertyAllowList: [
            () => [(_, props) => props.propertyAllowList],
            (propertyAllowList) => propertyAllowList as PersonPropertiesModelProps['propertyAllowList'],
        ],
    })),
    events(({ actions }) => ({
        afterMount: actions.loadPersonProperties,
    })),
])
