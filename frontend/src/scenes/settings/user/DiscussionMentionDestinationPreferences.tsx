import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonSkeleton, LemonTag } from '@posthog/lemon-ui'

import { userLogic } from 'scenes/userLogic'

import { discussionMentionDestinationsLogic } from './discussionMentionDestinationsLogic'

export function DiscussionMentionDestinationPreferences(): JSX.Element {
    const { projects, projectsLoading } = useValues(discussionMentionDestinationsLogic)
    const { user, userLoading } = useValues(userLogic)
    const { updateDiscussionMentionOptOut, updateDiscussionMentionOptOutForAllDestinations } = useActions(userLogic)

    const [expandedProjects, setExpandedProjects] = useState<Record<number, boolean>>({})

    if (projectsLoading) {
        return (
            <div className="space-y-4">
                <LemonSkeleton className="h-4 w-1/3" />
                <LemonSkeleton className="h-20 w-full" />
            </div>
        )
    }

    if (!projects.length) {
        return (
            <p className="text-muted-alt">
                No projects have discussion mention destinations configured. Admins can configure destinations in
                project settings.
            </p>
        )
    }

    const optOuts = user?.notification_settings?.discussion_mention_destination_opt_outs ?? {}

    const toggleProjectExpanded = (projectId: number): void => {
        setExpandedProjects((prev) => ({
            ...prev,
            [projectId]: !prev[projectId],
        }))
    }

    return (
        <div className="deprecated-space-y-4">
            {projects.map((project) => {
                const isExpanded = expandedProjects[project.id] ?? false
                const destinationIds = project.destinations.map((d) => d.id)

                return (
                    <div key={project.id} className="border rounded p-4 deprecated-space-y-3">
                        <div className="flex items-center gap-2">
                            <span className="font-semibold">{project.name}</span>
                            <LemonTag type="muted">id: {project.id}</LemonTag>
                        </div>

                        <LemonButton
                            icon={isExpanded ? <IconChevronDown /> : <IconChevronRight />}
                            onClick={() => toggleProjectExpanded(project.id)}
                            size="small"
                            type="tertiary"
                            className="p-0"
                        >
                            Select destinations ({project.destinations.length} available)
                        </LemonButton>

                        {isExpanded && (
                            <div className="mt-3 ml-6 deprecated-space-y-2">
                                <div className="flex flex-col gap-2">
                                    <div className="flex flex-row items-center gap-4">
                                        <LemonButton
                                            size="xsmall"
                                            type="secondary"
                                            onClick={() => {
                                                updateDiscussionMentionOptOutForAllDestinations(
                                                    project.id,
                                                    destinationIds,
                                                    false
                                                )
                                            }}
                                        >
                                            Enable all
                                        </LemonButton>
                                        <LemonButton
                                            size="xsmall"
                                            type="secondary"
                                            onClick={() => {
                                                updateDiscussionMentionOptOutForAllDestinations(
                                                    project.id,
                                                    destinationIds,
                                                    true
                                                )
                                            }}
                                        >
                                            Disable all
                                        </LemonButton>
                                    </div>

                                    {project.destinations.map((destination) => {
                                        const isOptedOut = (optOuts[project.id] ?? []).includes(destination.id)

                                        return (
                                            <LemonCheckbox
                                                key={destination.id}
                                                id={`discussion-mention-${project.id}-${destination.id}`}
                                                data-attr={`discussion_mention_${project.id}_${destination.id}`}
                                                onChange={(checked) => {
                                                    updateDiscussionMentionOptOut(project.id, destination.id, !checked)
                                                }}
                                                checked={!isOptedOut}
                                                disabled={userLoading}
                                                label={
                                                    <div className="flex items-center gap-2">
                                                        {destination.icon_url && (
                                                            <img
                                                                src={destination.icon_url}
                                                                alt=""
                                                                className="w-4 h-4 rounded"
                                                            />
                                                        )}
                                                        <span className="capitalize">{destination.type}</span>
                                                        <span className="text-muted-alt">- {destination.name}</span>
                                                    </div>
                                                }
                                            />
                                        )
                                    })}
                                </div>
                            </div>
                        )}
                    </div>
                )
            })}
        </div>
    )
}
