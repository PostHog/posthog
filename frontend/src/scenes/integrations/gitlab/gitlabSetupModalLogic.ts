import { connect, kea, path, props } from 'kea'
import { forms } from 'kea-forms'

import api from 'lib/api'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { lemonToast } from 'lib/lemon-ui/LemonToast'

import type { gitlabSetupModalLogicType } from './gitlabSetupModalLogicType'

export interface GitLabSetupModalLogicProps {
    isOpen: boolean
    onComplete: (integrationId?: number) => void
}

export const gitlabSetupModalLogic = kea<gitlabSetupModalLogicType>([
    path(['integrations', 'gitlab', 'gitlabSetupModalLogic']),
    props({} as GitLabSetupModalLogicProps),
    connect(() => ({
        actions: [integrationsLogic, ['loadIntegrations']],
    })),
    forms(({ props, actions, values }) => ({
        gitlabIntegration: {
            defaults: {
                hostname: 'https://gitlab.com',
                projectId: '',
                projectAccessToken: '',
            },
            errors: ({ hostname, projectId, projectAccessToken }) => ({
                hostname: hostname.trim() ? undefined : 'Hostname is required',
                projectId: projectId.trim() ? undefined : 'Project ID is required',
                projectAccessToken: projectAccessToken.trim() ? undefined : 'Project access token is required',
            }),
            submit: async () => {
                try {
                    const integration = await api.integrations.create({
                        kind: 'gitlab',
                        config: {
                            hostname: values.gitlabIntegration.hostname,
                            project_id: values.gitlabIntegration.projectId,
                            project_access_token: values.gitlabIntegration.projectAccessToken,
                        },
                    })
                    actions.loadIntegrations()
                    lemonToast.success('GitLab integration created successfully!')
                    props.onComplete(integration.id)
                } catch (error: any) {
                    lemonToast.error(error.detail || 'Failed to create GitLab integration')
                    throw error
                }
            },
        },
    })),
])
