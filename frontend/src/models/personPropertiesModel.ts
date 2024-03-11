import { connect, events, kea, key, listeners, path, props, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { combineUrl, router } from 'kea-router'
import api from 'lib/api'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { dataWarehouseJoinsLogic } from 'scenes/data-warehouse/external/dataWarehouseJoinsLogic'
import { teamLogic } from 'scenes/teamLogic'

import { updateListOfPropertyDefinitions } from '~/models/propertyDefinitionsModel'
import { PersonProperty, PropertyDefinition } from '~/types'

import type { personPropertiesModelType } from './personPropertiesModelType'
import { PersonPropertiesModelProps } from './types'

const WHITELISTED = ['/insights', '/events', '/sessions', '/dashboard', '/person']

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
    listeners(() => ({
        loadPersonPropertiesSuccess: ({ personProperties }) => {
            updateListOfPropertyDefinitions(
                personProperties as PropertyDefinition[],
                TaxonomicFilterGroupType.PersonProperties
            )
        },
    })),
    selectors(() => ({
        combinedPersonProperties: [
            (s) => [s.personProperties, s.columnsJoinedToPersons, s.featureFlags],
            (personProperties, columnsJoinedToPersons, featureFlags) => {
                // Hack to make sure person properties only show data warehouse in specific instances for now
                if (
                    featureFlags[FEATURE_FLAGS.DATA_WAREHOUSE] &&
                    WHITELISTED.some((path) => router.values.location.pathname.includes(path))
                ) {
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
