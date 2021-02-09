import { kea } from 'kea'
import { router } from 'kea-router'
import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'
import { navigationLogic } from '~/layout/navigation/navigationLogic'
import { OrganizationType, UserType } from '~/types'
import { onboardingSetupLogicType } from './onboardingSetupLogicType'

export const onboardingSetupLogic = kea<onboardingSetupLogicType>({
    actions: {
        switchToNonDemoProject: (dest) => ({ dest }),
        setProjectModalShown: (shown) => ({ shown }),
        setInviteTeamModalShown: (shown) => ({ shown }),
        completeOnboarding: true,
        callSlack: true,
    },
    reducers: {
        projectModalShown: [
            false,
            {
                setProjectModalShown: (_, { shown }) => shown,
            },
        ],
        inviteTeamModalShown: [
            false,
            {
                setInviteTeamModalShown: (_, { shown }) => shown,
            },
        ],
        slackCalled: [
            false,
            {
                callSlack: () => true,
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
                const teamId =
                    organizationLogic.values.currentOrganization?.setup.is_active &&
                    organizationLogic.values.currentOrganization?.setup.non_demo_team_id
                if (teamId) {
                    navigationLogic.actions.updateCurrentProject(teamId, dest)
                }
            }
        },
        completeOnboarding: () => {
            organizationLogic.actions.completeOnboarding()
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
            (organization: OrganizationType) =>
                organization.setup.is_active && organization.setup.any_project_ingested_events,
        ],
        stepVerification: [
            (selectors) => [organizationLogic.selectors.currentOrganization, selectors.stepInstallation],
            (organization: OrganizationType, stepInstallation: boolean) =>
                stepInstallation &&
                organization.setup.is_active &&
                organization.setup.any_project_completed_snippet_onboarding,
        ],
        currentSection: [
            () => [organizationLogic.selectors.currentOrganization],
            (organization: OrganizationType): number | null => organization.setup.current_section,
        ],
        teamInviteAvailable: [
            () => [userLogic.selectors.user],
            (user: UserType): boolean => user.email_service_available,
        ],
        progressPercentage: [
            (s) => [
                s.teamInviteAvailable,
                userLogic.selectors.user,
                organizationLogic.selectors.currentOrganization,
                s.stepProjectSetup,
                s.stepInstallation,
                s.stepVerification,
                s.slackCalled,
            ],
            (
                teamInviteAvailable: boolean,
                user: UserType,
                currentOrganization: OrganizationType,
                ...steps: boolean[]
            ): number => {
                if (teamInviteAvailable) {
                    steps.push(
                        currentOrganization.setup.is_active && currentOrganization.setup.has_invited_team_members
                    )
                }
                steps.push(user.team ? user.team.session_recording_opt_in : false)
                const completed_steps = steps.reduce((acc, step) => acc + (step ? 1 : 0), 0)
                return Math.round((completed_steps / steps.length) * 100)
            },
        ],
    },
})
