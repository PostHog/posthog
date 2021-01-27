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
                let teamId = null
                if (user.organization?.teams) {
                    for (const team of user.organization?.teams) {
                        if (!team.is_demo) {
                            teamId = team.id
                        }
                    }
                }
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
            (organization: OrganizationType) => {
                // Step is completed if the user has ingested an event in any non-demo project
                if (organization.teams) {
                    for (const team of organization.teams) {
                        if (!team.is_demo && team.ingested_event) {
                            return true
                        }
                    }
                }

                return false
            },
        ],
        stepVerification: [
            (selectors) => [organizationLogic.selectors.currentOrganization, selectors.stepInstallation],
            (organization: OrganizationType, stepInstallation: boolean) => {
                // Step is completed if the user has completed the snippet onboarding in any non-demo project
                if (stepInstallation && organization.teams) {
                    for (const team of organization.teams) {
                        if (!team.is_demo && team.completed_snippet_onboarding) {
                            return true
                        }
                    }
                }

                return false
            },
        ],
    },
})
