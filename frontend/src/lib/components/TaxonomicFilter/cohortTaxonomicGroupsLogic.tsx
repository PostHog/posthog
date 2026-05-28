import { connect, kea, key, path, props, selectors } from 'kea'
import { combineUrl } from 'kea-router'

import {
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterLogicProps,
} from 'lib/components/TaxonomicFilter/types'
import { IconCohort } from 'lib/lemon-ui/icons'
import { Link } from 'lib/lemon-ui/Link'
import { COHORT_BEHAVIORAL_LIMITATIONS_URL } from 'scenes/feature-flags/constants'
import { projectLogic } from 'scenes/projectLogic'

import { CohortType } from '~/types'

import type { cohortTaxonomicGroupsLogicType } from './cohortTaxonomicGroupsLogicType'

// Stable reference for CohortsWithAllUsers options to prevent cascading re-renders.
// taxonomicGroups has 14 dependencies that change during initial mount. Each change creates
// new group objects with inline options arrays, causing rawLocalItems → fuse → localItems →
// items → selectedItem reference changes. With CohortsWithAllUsers, selectedItemHasPopover
// returns true (getValue returns 'all'), so ControlledDefinitionPopover renders and its
// useEffect dispatches setDefinition on every selectedItem change, triggering kea store updates
// that combined with react-window's layout effect setState exceed React's 50-update limit.
const COHORTS_WITH_ALL_USERS_OPTIONS: CohortType[] = [{ id: 'all', name: 'All Users*' } as unknown as CohortType]

export const cohortTaxonomicGroupsLogic = kea<cohortTaxonomicGroupsLogicType>([
    props({} as TaxonomicFilterLogicProps),
    key((props) => `${props.taxonomicFilterLogicKey}`),
    path((key) => ['lib', 'components', 'TaxonomicFilter', 'cohortTaxonomicGroupsLogic', key]),

    connect(() => ({
        values: [projectLogic, ['currentProjectId']],
    })),

    selectors({
        hideBehavioralCohorts: [
            () => [(_, props) => props.hideBehavioralCohorts],
            (hideBehavioralCohorts: boolean | undefined) => hideBehavioralCohorts ?? false,
        ],
        cohortTaxonomicGroups: [
            (s) => [s.currentProjectId, s.hideBehavioralCohorts],
            (projectId, hideBehavioralCohorts): TaxonomicFilterGroup[] => [
                {
                    name: 'Cohorts',
                    searchPlaceholder: 'cohorts',
                    type: TaxonomicFilterGroupType.Cohorts,
                    endpoint: combineUrl(`api/projects/${projectId}/cohorts/`).url,
                    value: 'cohorts',
                    getName: (cohort: CohortType) => cohort.name || `Cohort ${cohort.id}`,
                    getValue: (cohort: CohortType) => cohort.id,
                    getPopoverHeader: (cohort: CohortType) => `${cohort.is_static ? 'Static' : 'Dynamic'} Cohort`,
                    getIcon: function _getIcon(): JSX.Element {
                        return <IconCohort className="taxonomy-icon taxonomy-icon-muted" />
                    },
                    footerMessage: hideBehavioralCohorts ? (
                        <>
                            <Link to={COHORT_BEHAVIORAL_LIMITATIONS_URL} target="_blank">
                                Some cohorts excluded due to containing behavioral filters.
                            </Link>
                        </>
                    ) : undefined,
                },
                {
                    name: 'Cohorts',
                    searchPlaceholder: 'cohorts',
                    type: TaxonomicFilterGroupType.CohortsWithAllUsers,
                    endpoint: combineUrl(`api/projects/${projectId}/cohorts/`).url,
                    options: COHORTS_WITH_ALL_USERS_OPTIONS,
                    getName: (cohort: CohortType) => cohort.name || `Cohort ${cohort.id}`,
                    getValue: (cohort: CohortType) => cohort.id,
                    getPopoverHeader: () => `All Users`,
                    getIcon: function _getIcon(): JSX.Element {
                        return <IconCohort className="taxonomy-icon taxonomy-icon-muted" />
                    },
                },
            ],
        ],
    }),
])
