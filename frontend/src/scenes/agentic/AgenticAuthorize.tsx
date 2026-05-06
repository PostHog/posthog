import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { IconCheck } from '@posthog/icons'
import { LemonLabel } from '@posthog/lemon-ui'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCard } from 'lib/lemon-ui/LemonCard/LemonCard'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { OAuthAuthorizeError } from 'scenes/oauth/OAuthAuthorize'
import { OrganizationSelector } from 'scenes/settings/user/scopes/ScopeAccessSelector/OrganizationSelector'
import { TeamSelector } from 'scenes/settings/user/scopes/ScopeAccessSelector/TeamSelector'

import { SceneExport } from '../sceneTypes'
import { agenticAuthorizeLogic } from './agenticAuthorizeLogic'

export const AgenticAuthorize = (): JSX.Element => {
    const {
        scopeDescriptions,
        allOrganizations,
        filteredTeams,
        allTeamsLoading,
        pendingAuthLoading,
        state,
        partnerName,
        agenticAuthorization,
        isAgenticAuthorizationSubmitting,
    } = useValues(agenticAuthorizeLogic)
    const { cancel, submitAgenticAuthorization, setAgenticAuthorizationValue } = useActions(agenticAuthorizeLogic)

    if (!state) {
        return <OAuthAuthorizeError title="Invalid request" description="Missing required state parameter." />
    }

    if (allTeamsLoading || pendingAuthLoading) {
        return (
            <div className="flex items-center justify-center h-full py-12">
                <Spinner />
            </div>
        )
    }

    const selectedOrgId = agenticAuthorization.scoped_organizations[0]

    return (
        <div className="min-h-full overflow-y-auto">
            <div className="max-w-2xl mx-auto py-8 px-4 sm:py-12 sm:px-6">
                <div className="text-center mb-4 sm:mb-8">
                    <h2 className="text-xl sm:text-2xl font-semibold">
                        Authorize <strong>{partnerName}</strong>
                    </h2>
                    <p className="text-muted mt-2 text-sm sm:text-base">
                        {partnerName} is requesting access to your PostHog project.
                    </p>
                </div>

                <Form logic={agenticAuthorizeLogic} formKey="agenticAuthorization">
                    <LemonCard hoverEffect={false} className="p-4 sm:p-6">
                        <div className="flex flex-col gap-2">
                            <LemonLabel>Select organization</LemonLabel>
                            <LemonField name="scoped_organizations">
                                {({ value, onChange }) => (
                                    <OrganizationSelector
                                        organizations={allOrganizations}
                                        mode="single"
                                        value={value?.length > 0 ? [value[0]] : []}
                                        onChange={(val: string[]) => {
                                            onChange(val.length > 0 ? [val[0]] : [])
                                            setAgenticAuthorizationValue('scoped_teams', [])
                                        }}
                                    />
                                )}
                            </LemonField>
                        </div>

                        <div className="flex flex-col gap-2 mt-4">
                            <LemonLabel>Select project</LemonLabel>
                            <LemonField name="scoped_teams">
                                {({ value, onChange }) => (
                                    <TeamSelector
                                        teams={filteredTeams}
                                        organizations={allOrganizations}
                                        mode="single"
                                        value={value?.length > 0 ? [String(value[0])] : []}
                                        onChange={(val: string[]) => onChange(val.length > 0 ? [parseInt(val[0])] : [])}
                                    />
                                )}
                            </LemonField>
                            {!selectedOrgId && (
                                <p className="text-xs text-muted">Select an organization first to see its projects.</p>
                            )}
                        </div>

                        {scopeDescriptions.length > 0 && (
                            <>
                                <LemonDivider className="my-4" />
                                <div>
                                    <div className="text-sm font-semibold uppercase text-muted mb-2">
                                        Requested permissions
                                    </div>
                                    <ul className="space-y-2">
                                        {scopeDescriptions.map((scopeDescription: string, idx: number) => (
                                            <li key={idx} className="flex items-center space-x-2">
                                                <IconCheck color="var(--success)" />
                                                <span className="font-medium">{scopeDescription}</span>
                                            </li>
                                        ))}
                                    </ul>
                                </div>
                            </>
                        )}

                        <LemonDivider className="my-4" />

                        <div className="flex flex-col-reverse sm:flex-row sm:justify-end gap-2">
                            <LemonButton
                                type="secondary"
                                htmlType="button"
                                disabledReason={isAgenticAuthorizationSubmitting ? 'Processing...' : undefined}
                                onClick={(e) => {
                                    e.preventDefault()
                                    cancel()
                                }}
                            >
                                Cancel
                            </LemonButton>
                            <LemonButton
                                type="primary"
                                htmlType="submit"
                                loading={isAgenticAuthorizationSubmitting}
                                disabledReason={isAgenticAuthorizationSubmitting ? 'Authorizing...' : undefined}
                                onClick={() => submitAgenticAuthorization()}
                            >
                                Authorize {partnerName}
                            </LemonButton>
                        </div>
                    </LemonCard>
                </Form>
            </div>
        </div>
    )
}

export const scene: SceneExport = {
    component: AgenticAuthorize,
    logic: agenticAuthorizeLogic,
}
