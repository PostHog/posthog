import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconEllipsis } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { urls } from 'scenes/urls'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { openCreateScorerVersionDialog } from './openCreateScorerVersionDialog'
import { ScorerLogicProps, scorerLogic } from './scorerLogic'

export function QuillAIObservabilityScorerActions(props: ScorerLogicProps): JSX.Element {
    const logic = scorerLogic(props)
    const { definition, isNew, hasChanges, saving } = useValues(logic)
    const { createVersion, toggleArchive } = useActions(logic)
    const editDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.LlmAnalytics,
        AccessControlLevel.Editor
    )
    const changeDisabledReason =
        editDisabledReason || (saving ? 'Saving scorer' : hasChanges ? 'Save your changes first' : undefined)

    return (
        <div className="flex flex-wrap items-center gap-2">
            {!isNew && definition && (
                <DropdownMenu>
                    <DropdownMenuTrigger
                        render={
                            <Button
                                variant="outline"
                                size="icon"
                                aria-label="Scorer actions"
                                tooltip="Scorer actions"
                            />
                        }
                    >
                        <IconEllipsis />
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                        <DropdownMenuItem
                            disabledReason={editDisabledReason || (saving ? 'Saving scorer' : undefined)}
                            onClick={() =>
                                router.actions.push(urls.aiObservabilityScorer('new', { duplicate: definition.id }))
                            }
                            data-attr="llma-scorer-duplicate"
                        >
                            Duplicate
                        </DropdownMenuItem>
                        <DropdownMenuItem
                            disabledReason={changeDisabledReason}
                            onClick={() =>
                                openCreateScorerVersionDialog({
                                    currentVersion: definition.current_version,
                                    createVersion,
                                })
                            }
                            data-attr="llma-scorer-new-version"
                        >
                            Create new version
                        </DropdownMenuItem>
                        <DropdownMenuItem
                            variant={definition.archived ? 'default' : 'destructive'}
                            disabledReason={changeDisabledReason}
                            onClick={toggleArchive}
                            data-attr="llma-scorer-archive-toggle"
                        >
                            {definition.archived ? 'Unarchive' : 'Archive'}
                        </DropdownMenuItem>
                    </DropdownMenuContent>
                </DropdownMenu>
            )}
            <Button
                variant="outline"
                render={<LinkPrimitive to={urls.aiObservabilityScorers()} />}
                disabledReason={saving ? 'Saving scorer' : undefined}
                data-attr="llma-scorer-cancel"
            >
                {hasChanges || isNew ? 'Cancel' : 'Back to scorers'}
            </Button>
            <Button
                variant="primary"
                type="submit"
                form="scorer-form"
                loading={saving}
                disabledReason={editDisabledReason || (!hasChanges ? 'No unsaved changes' : undefined)}
                data-attr="llma-scorer-save"
            >
                {isNew ? 'Create scorer' : 'Save changes'}
            </Button>
        </div>
    )
}
