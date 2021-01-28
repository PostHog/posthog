import { kea } from 'kea'
import { router } from 'kea-router'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'
import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { OrganizationType } from '~/types'
import { onboardingSetupLogicType } from './onboardingSetupLogicType'

export const onboardingSetupLogic = kea<onboardingSetupLogicType>({
    actions: {
        switchToNonDemoProject: (dest) => ({ dest }),
        setProjectModalShown: (shown) => ({ shown }),
    },
    reducers: {
        projectModalShown: [
            false,
            {
                setProjectModalShown: (_, { shown }) => shown,
            },
        ],
    },
    listeners: {
        switchToNonDemoProject: ({ dest }: { dest: string }) => {
            // Swithces to the first non-demo project (if on demo) and takes user to dest
            const { user } = userLogic.values
            if (!user?.team?.is_demo) {
                router.actions.push(dest)
            } else {
                const teamId = organizationLogic.values.currentOrganization?.non_demo_team_id
                if (teamId) {
                    navigationLogic.actions.updateCurrentProject(teamId, dest)
                }
            }
        },
    },
    selectors: {
        // All `step{Key}` selectors represent whether a step has been completed or not
        stepProjectSetup: [
            () => [userLogic.selectors.demoOnlyProject],
            (demoOnlyProject: boolean) => {
                // Step is completed if org has at least one non-demo project
                return !demoOnlyProject
            },
        ],
        stepInstallation: [
            () => [organizationLogic.selectors.currentOrganization],
            (organization: OrganizationType) => organization.any_project_ingested_events,
        ],
        stepVerification: [
            (selectors) => [organizationLogic.selectors.currentOrganization, selectors.stepInstallation],
            (organization: OrganizationType, stepInstallation: boolean) =>
                stepInstallation && organization.any_project_completed_snippet_onboarding,
        ],
    },
})
