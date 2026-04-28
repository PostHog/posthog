import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useEffect } from 'react'

import { LemonButton, LemonSkeleton, LemonTextArea } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { sessionSummariesConfigLogic } from 'scenes/session-recordings/player/sessionSummariesConfigLogic'

const PRODUCT_CONTEXT_PLACEHOLDER = `Example:

We're a B2B project management tool for software teams. Key events include creating projects, inviting team members, and completing sprints. A "Workspace" is a team's shared environment.

Free users see an upgrade modal when they try to export — this is intentional, not an error.

Users often switch between board view and list view rapidly when comparing tasks — normal behavior, not confusion.`

export function SessionSummariesSettings(): JSX.Element {
    const { isLoading, isUpdating } = useValues(sessionSummariesConfigLogic)
    const { revertConfigForm } = useActions(sessionSummariesConfigLogic)
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    useEffect(() => {
        revertConfigForm()
    }, [revertConfigForm])

    return (
        <Form
            logic={sessionSummariesConfigLogic}
            formKey="configForm"
            enableFormOnSubmit
            className="deprecated-space-y-4"
        >
            {isLoading ? (
                <div className="gap-2 flex flex-col">
                    <LemonSkeleton className="h-6 w-32" />
                    <LemonSkeleton className="h-48" />
                </div>
            ) : (
                <LemonField name="product_context" label="Product context">
                    <LemonTextArea
                        placeholder={PRODUCT_CONTEXT_PLACEHOLDER}
                        maxLength={10000}
                        minRows={10}
                        maxRows={24}
                        disabled={!!restrictedReason}
                    />
                </LemonField>
            )}
            <div className="flex justify-end">
                <LemonButton
                    type="primary"
                    htmlType="submit"
                    disabledReason={isLoading ? 'Loading…' : restrictedReason}
                    loading={isUpdating}
                >
                    Save
                </LemonButton>
            </div>
        </Form>
    )
}
