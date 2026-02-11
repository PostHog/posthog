import { useActions, useValues } from 'kea'
import { useCallback, useState } from 'react'

import { LemonButton, LemonInputSelect, LemonSelect, LemonSkeleton } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import {
    type PreviewResource,
    type ResourceTransferLogicProps,
    type SubstitutionChoice,
    resourceTransferLogic,
} from './resourceTransferLogic'

export const scene: SceneExport<ResourceTransferLogicProps> = {
    component: ResourceTransfer,
    logic: resourceTransferLogic,
    paramsToProps: ({ params: { resourceKind, resourceId } }) => ({ resourceKind, resourceId }),
}

export function ResourceTransfer(props: ResourceTransferLogicProps): JSX.Element {
    const logic = resourceTransferLogic(props)
    const {
        destinationTeamId,
        preview,
        previewLoading,
        transferResultLoading,
        teamOptions,
        substitutionChoices,
        userFacingResources,
        rootResourceName,
    } = useValues(logic)
    const { setDestinationTeamId, submitTransfer, setSubstitutionChoice } = useActions(logic)

    const title = rootResourceName
        ? `Copy "${rootResourceName}" to another project`
        : `Copy ${props.resourceKind.toLowerCase()} to another project`

    return (
        <SceneContent>
            <SceneTitleSection
                name={title}
                resourceType={{ type: undefined }}
                forceBackTo={{
                    name: rootResourceName ?? props.resourceKind,
                    path: sourceResourceUrl(props.resourceKind, props.resourceId),
                    key: 'resource-transfer-back',
                }}
            />
            <div className="max-w-160 mt-4 mb-16 space-y-6">
                <div className="space-y-2">
                    <p>
                        Choose which project to copy this resource and its dependencies to. The original will not be
                        modified.
                    </p>
                    <div>
                        <label className="font-semibold leading-6 block mb-1">Destination project</label>
                        <LemonSelect
                            fullWidth
                            placeholder="Select a project"
                            value={destinationTeamId}
                            onChange={(value) => setDestinationTeamId(value)}
                            options={teamOptions}
                        />
                    </div>
                    {teamOptions.length === 0 && (
                        <p className="text-muted text-sm">
                            There are no other projects in your organization to copy to. Create another project first.
                        </p>
                    )}
                </div>

                {destinationTeamId && (
                    <>
                        {previewLoading ? (
                            <div className="space-y-3">
                                <LemonSkeleton className="h-10 w-full" />
                                <LemonSkeleton className="h-10 w-full" />
                                <LemonSkeleton className="h-10 w-full" />
                            </div>
                        ) : preview ? (
                            <div className="space-y-4">
                                {userFacingResources.length > 0 && (
                                    <div className="space-y-3">
                                        <label className="font-semibold leading-6 block">Dependencies</label>
                                        <p className="text-sm text-muted">
                                            For each dependency, choose whether to create a new copy or use an existing
                                            resource in the destination project.
                                        </p>
                                        {userFacingResources.map((resource) => {
                                            const key = `${resource.resource_kind}:${resource.resource_id}`
                                            const choice = substitutionChoices[key] ?? { mode: 'copy' }
                                            return (
                                                <ResourceRow
                                                    key={key}
                                                    resource={resource}
                                                    resourceKey={key}
                                                    choice={choice}
                                                    onChoiceChange={setSubstitutionChoice}
                                                    logic={logic}
                                                />
                                            )
                                        })}
                                    </div>
                                )}
                                <div className="flex justify-end">
                                    <LemonButton
                                        type="primary"
                                        onClick={submitTransfer}
                                        loading={transferResultLoading}
                                    >
                                        Copy
                                    </LemonButton>
                                </div>
                            </div>
                        ) : null}
                    </>
                )}
            </div>
        </SceneContent>
    )
}

function sourceResourceUrl(resourceKind: string, resourceId: string): string {
    switch (resourceKind) {
        case 'Dashboard':
            return urls.dashboard(resourceId)
        case 'Insight':
            return urls.insightView(resourceId as any)
        default:
            return urls.projectHomepage()
    }
}

function ResourceRow({
    resource,
    resourceKey,
    choice,
    onChoiceChange,
    logic,
}: {
    resource: PreviewResource
    resourceKey: string
    choice: SubstitutionChoice
    onChoiceChange: (resourceKey: string, choice: SubstitutionChoice) => void
    logic: ReturnType<typeof resourceTransferLogic>
}): JSX.Element {
    const { searchResources } = useActions(logic)
    const { searchResults, searchResultsLoading } = useValues(logic)

    const [isSearching, setIsSearching] = useState(false)

    const handleModeChange = useCallback(
        (mode: string | null) => {
            if (mode === 'copy') {
                onChoiceChange(resourceKey, { mode: 'copy' })
                setIsSearching(false)
            } else if (mode === 'substitute') {
                setIsSearching(true)
                searchResources(resource.resource_kind, '')
            }
        },
        [resourceKey, resource.resource_kind, onChoiceChange, searchResources]
    )

    const handleSearchInput = useCallback(
        (query: string) => {
            searchResources(resource.resource_kind, query)
        },
        [resource.resource_kind, searchResources]
    )

    const handleSubstitutionSelect = useCallback(
        (values: string[]) => {
            const selectedId = values[0]
            if (!selectedId) {
                return
            }
            const result = searchResults?.results.find((r) => r.resource_id === selectedId)
            if (result) {
                onChoiceChange(resourceKey, {
                    mode: 'substitute',
                    resource_kind: result.resource_kind,
                    resource_id: result.resource_id,
                    display_name: result.display_name,
                })
                setIsSearching(false)
            }
        },
        [searchResults, resourceKey, onChoiceChange]
    )

    const modeValue = isSearching || choice.mode === 'substitute' ? 'substitute' : 'copy'

    return (
        <div className="border rounded p-3 space-y-2">
            <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 min-w-0">
                    <span className="font-medium truncate">{resource.display_name}</span>
                    <span className="text-muted text-xs shrink-0">{resource.friendly_kind}</span>
                </div>
                <LemonSelect
                    size="small"
                    value={modeValue}
                    onChange={handleModeChange}
                    options={[
                        { value: 'copy', label: 'Copy' },
                        { value: 'substitute', label: 'Use existing' },
                    ]}
                />
            </div>

            {choice.mode === 'substitute' && !isSearching && (
                <div className="text-sm text-muted pl-2 flex items-center gap-1">
                    Linked to: <span className="font-medium text-default">{choice.display_name}</span>
                    <LemonButton size="xsmall" type="tertiary" onClick={() => setIsSearching(true)}>
                        Change
                    </LemonButton>
                </div>
            )}

            {isSearching && (
                <div className="pl-2">
                    <LemonInputSelect
                        mode="single"
                        placeholder={`Search for ${resource.friendly_kind.toLowerCase()}...`}
                        options={
                            searchResults?.results.map((r) => ({
                                key: r.resource_id,
                                label: r.display_name,
                            })) ?? []
                        }
                        loading={searchResultsLoading}
                        disableFiltering
                        onInputChange={handleSearchInput}
                        onChange={handleSubstitutionSelect}
                        value={null}
                    />
                </div>
            )}

            {resource.suggested_substitution && choice.mode === 'copy' && (
                <div className="text-xs text-muted pl-2">
                    Previously copied to:{' '}
                    <LemonButton
                        size="xsmall"
                        type="tertiary"
                        onClick={() =>
                            onChoiceChange(resourceKey, {
                                mode: 'substitute',
                                resource_kind: resource.suggested_substitution!.resource_kind,
                                resource_id: resource.suggested_substitution!.resource_id,
                                display_name: resource.suggested_substitution!.display_name,
                            })
                        }
                    >
                        {resource.suggested_substitution.display_name}
                    </LemonButton>
                </div>
            )}
        </div>
    )
}
