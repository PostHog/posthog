import { actions, kea, key, connect, propsChanged, listeners, path, props, reducers, selectors } from 'kea'
import { BehavioralFilterKey, FieldOptionsType, FieldValues } from 'scenes/cohorts/CohortFilters/types'
import { FIELD_VALUES, SCALE_FIELD_VALUES } from 'scenes/cohorts/CohortFilters/constants'
import { groupsModel } from '~/models/groupsModel'
import { ActorGroupType, AnyCohortCriteriaType, AvailableFeature } from '~/types'
import type { cohortFieldLogicType } from './cohortFieldLogicType'
import { cleanBehavioralTypeCriteria, resolveCohortFieldValue } from 'scenes/cohorts/cohortUtils'
import { cohortsModel } from '~/models/cohortsModel'
import { actionsModel } from '~/models/actionsModel'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { objectsEqual } from 'lib/utils'
import { userLogic } from 'scenes/userLogic'

export interface CohortFieldLogicProps {
    cohortFilterLogicKey: string
    fieldKey: keyof AnyCohortCriteriaType
    criteria: AnyCohortCriteriaType
    onChange?: (newField: AnyCohortCriteriaType) => void
    /* Only used for selector fields */
    fieldOptionGroupTypes?: FieldOptionsType[]
}

export const cohortFieldLogic = kea<cohortFieldLogicType>([
    path(['scenes', 'cohorts', 'CohortFilters', 'cohortFieldLogic']),
    key((props) => `${props.cohortFilterLogicKey}`),
    props({} as CohortFieldLogicProps),
    connect({
        values: [groupsModel, ['groupTypes', 'aggregationLabel'], userLogic, ['hasAvailableFeature']],
    }),
    propsChanged(({ actions, props }, oldProps) => {
        if (props.fieldKey && !objectsEqual(props.criteria, oldProps.criteria)) {
            actions.onChange(props.criteria)
        }
    }),
    actions({
        onChange: (newField: AnyCohortCriteriaType) => ({ newField }),
    }),
    reducers(({ props }) => ({
        value: [
            resolveCohortFieldValue(props.criteria, props.fieldKey),
            {
                onChange: (_, { newField }) =>
                    resolveCohortFieldValue({ ...props.criteria, ...newField }, props.fieldKey),
            },
        ],
    })),
    selectors({
        hasBehavioralCohortFiltering: [
            (s) => [s.hasAvailableFeature],
            (hasAvailableFeature) => hasAvailableFeature(AvailableFeature.BEHAVIORAL_COHORT_FILTERING),
        ],
        fieldOptionGroups: [
            (s) => [
                (_, props) => props.fieldOptionGroupTypes,
                s.groupTypes,
                s.aggregationLabel,
                s.hasBehavioralCohortFiltering,
            ],
            (fieldOptionGroupTypes, groupTypes, aggregationLabel, hasBehavioralCohortFiltering): FieldValues[] => {
                const fieldOptions = hasBehavioralCohortFiltering
                    ? { ...FIELD_VALUES, ...SCALE_FIELD_VALUES }
                    : FIELD_VALUES

                const allGroups = {
                    ...fieldOptions,
                    [FieldOptionsType.Actors]: {
                        label: 'Actors',
                        type: FieldOptionsType.Actors,
                        values: {
                            [ActorGroupType.Person]: {
                                label: 'Persons',
                            },
                            ...Object.fromEntries(
                                groupTypes.map((type) => [
                                    `${ActorGroupType.GroupPrefix}_${type.group_type_index}`,
                                    { label: aggregationLabel(type.group_type_index).plural },
                                ])
                            ),
                        },
                    },
                }
                return [...(fieldOptionGroupTypes?.map((type: FieldOptionsType) => allGroups[type]) ?? [])]
            },
        ],
        currentOption: [
            (s) => [s.fieldOptionGroups, s.value],
            (fieldOptionGroups, value) =>
                value && typeof value === 'string'
                    ? fieldOptionGroups.reduce((accumulator, group) => ({ ...accumulator, ...group.values }), {})?.[
                          value
                      ]
                    : null,
        ],
        calculatedValueLoading: [
            (s) => [
                s.value,
                (_, props) => props.criteria,
                (_, props) => props.fieldKey,
                cohortsModel.selectors.cohortsLoading,
                actionsModel.selectors.actionsLoading,
            ],
            (value, criteria, fieldKey, cohortsModelLoading, actionsModelLoading) =>
                (taxonomicGroupType: TaxonomicFilterGroupType) => {
                    return (
                        (criteria.type === BehavioralFilterKey.Cohort &&
                            fieldKey === 'value_property' &&
                            typeof value === 'number' &&
                            cohortsModelLoading) ||
                        (taxonomicGroupType === TaxonomicFilterGroupType.Actions &&
                            typeof value === 'number' &&
                            actionsModelLoading)
                    )
                },
        ],
        calculatedValue: [
            (s) => [
                s.value,
                (_, props) => props.criteria,
                (_, props) => props.fieldKey,
                cohortsModel.selectors.cohortsLoading,
                actionsModel.selectors.actionsLoading,
            ],
            (value, criteria, fieldKey, cohortsModelLoading, actionsModelLoading) =>
                (taxonomicGroupType: TaxonomicFilterGroupType) => {
                    // Only used by taxonomic filter field to determine label name
                    if (
                        criteria.type === BehavioralFilterKey.Cohort &&
                        fieldKey === 'value_property' &&
                        typeof value === 'number'
                    ) {
                        if (cohortsModelLoading) {
                            return 'Loading...'
                        }
                        return cohortsModel.findMounted()?.values?.cohortsById?.[value]?.name ?? `Cohort ${value}`
                    }
                    if (taxonomicGroupType === TaxonomicFilterGroupType.Actions && typeof value === 'number') {
                        if (actionsModelLoading) {
                            return 'Loading...'
                        }
                        return actionsModel.findMounted()?.values?.actionsById?.[value]?.name ?? `Action ${value}`
                    }
                    return value
                },
        ],
    }),
    listeners(({ props }) => ({
        onChange: ({ newField }) => {
            props.onChange?.(cleanBehavioralTypeCriteria(newField))
        },
    })),
])
