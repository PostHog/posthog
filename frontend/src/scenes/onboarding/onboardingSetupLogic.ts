import { kea } from 'kea'
import { router } from 'kea-router'
import { userLogic } from 'scenes/userLogic'
import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { UserType } from '~/types'
import { onboardingSetupLogicType } from './onboardingSetupLogicType'

export const onboardingSetupLogic = kea<onboardingSetupLogicType>({
    actions: {
        switchToNonDemoProject: (dest) => ({ dest }),
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
            () => [userLogic.selectors.user],
            (user: UserType) => {
                // Step is completed if the user has ingested an event in any non-demo project
                if (user.organization?.teams) {
                    for (const team of user.organization?.teams) {
                        if (!team.is_demo && user.team?.ingested_event) {
                            return true
                        }
                    }
                }

                return false
            },
        ],
    },
})
