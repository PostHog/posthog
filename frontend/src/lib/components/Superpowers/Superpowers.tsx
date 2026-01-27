import { useActions, useValues } from 'kea'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonDivider } from '@posthog/lemon-ui'

import { SupermanHog } from 'lib/components/hedgehogs'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { openCHQueriesDebugModal } from '../AppShortcuts/utils/DebugCHQueries'
import { superpowersLogic } from './superpowersLogic'

export function SuperpowersModal(): JSX.Element | null {
    const { isSuperpowersOpen } = useValues(superpowersLogic)
    const { closeSuperpowers } = useActions(superpowersLogic)

    return (
        <LemonModal title="" isOpen={isSuperpowersOpen} onClose={closeSuperpowers} width={500}>
            <SuperpowersContent />
        </LemonModal>
    )
}

function SuperpowersContent(): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam } = useActions(teamLogic)
    const { user } = useValues(userLogic)
    const { closeSuperpowers } = useActions(superpowersLogic)

    const clearOnboardingTasks = (): void => {
        updateCurrentTeam({ onboarding_tasks: {} })
    }

    const handleOpenCHQueries = (): void => {
        closeSuperpowers()
        openCHQueriesDebugModal()
    }

    return (
        <div className="space-y-4">
            {/* Hero section */}
            <div className="flex items-center gap-4 -mt-2">
                <SupermanHog className="w-24 h-24 shrink-0" />
                <div>
                    <h2 className="text-xl font-bold mb-1">Super Hog Powers</h2>
                    <p className="text-secondary text-sm">
                        With great power comes great responsibility. Use these wisely, fellow hog.
                    </p>
                </div>
            </div>

            <LemonDivider />

            <div>
                <h3 className="font-semibold mb-2">Quick start / Onboarding</h3>
                <div className="space-y-2">
                    <div className="flex items-center justify-between p-2 border rounded">
                        <div>
                            <div className="font-medium">Clear all onboarding tasks</div>
                            <div className="text-sm text-secondary">
                                Reset all quick start task progress for this team
                            </div>
                        </div>
                        <LemonButton
                            type="secondary"
                            status="danger"
                            icon={<IconTrash />}
                            size="small"
                            onClick={clearOnboardingTasks}
                        >
                            Clear
                        </LemonButton>
                    </div>
                    <div className="text-xs text-secondary font-mono p-2 bg-surface-tertiary rounded max-h-40 overflow-auto whitespace-pre">
                        Current tasks: {JSON.stringify(currentTeam?.onboarding_tasks || {}, null, 2)}
                    </div>
                </div>
            </div>

            <LemonDivider />

            <div>
                <h3 className="font-semibold mb-2">Debug tools</h3>
                <div className="space-y-2">
                    <div className="flex items-center justify-between p-2 border rounded">
                        <div>
                            <div className="font-medium">ClickHouse queries</div>
                            <div className="text-sm text-secondary">View recent ClickHouse queries for this user</div>
                        </div>
                        <LemonButton type="secondary" size="small" onClick={handleOpenCHQueries}>
                            Open
                        </LemonButton>
                    </div>
                </div>
            </div>

            <LemonDivider />

            <div className="text-xs text-secondary">
                <div>
                    User: {user?.email} {user?.is_staff ? '(staff)' : ''}{' '}
                    {user?.is_impersonated ? '(impersonated)' : ''}
                </div>
                <div>Team ID: {currentTeam?.id}</div>
            </div>
        </div>
    )
}
