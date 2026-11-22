import { LogicWrapper } from 'kea'
import { ReactNode } from 'react'

import { IconCheck, IconPencil, IconTrash, IconX } from '@posthog/icons'
import { Button, Item, ItemActions, ItemContent, ItemTitle, Text } from '@posthog/quill'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { cn } from 'lib/utils/css-classes'

import { UrlTriggerConfig } from '../types'
import { QuillUrlConfigForm } from './QuillUrlConfigForm'
import { confirmRemoveUrl } from './UrlConfig'

export function QuillUrlConfigRow({
    trigger,
    index,
    editIndex,
    onEdit,
    onRemove,
    checkUrlResult,
    logic,
    logicProps,
    formKey,
    validationWarning,
    aiRegexHelper,
}: {
    trigger: UrlTriggerConfig
    index: number
    editIndex: number | null
    onEdit: (index: number) => void
    onRemove: (index: number) => void
    checkUrlResult?: boolean
    logic: LogicWrapper
    logicProps: Record<string, any>
    formKey: string
    validationWarning: string | null
    aiRegexHelper?: ReactNode
}): JSX.Element {
    const restrictedReason = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Admin,
    })

    if (editIndex === index) {
        return (
            <QuillUrlConfigForm
                logic={logic}
                logicProps={logicProps}
                formKey={formKey}
                aiRegexHelper={aiRegexHelper}
                validationWarning={validationWarning}
                onCancel={() => onEdit(-1)}
                isSubmitting={false}
            />
        )
    }

    return (
        <Item
            variant="outline"
            size="sm"
            className={cn('flex-wrap', {
                'border-success-foreground': checkUrlResult === true,
                'border-destructive-foreground': checkUrlResult === false,
            })}
        >
            <ItemContent className="min-w-0">
                <ItemTitle className="w-full min-w-0">
                    <span title={trigger.url} className="truncate">
                        {`${trigger.matching === 'regex' ? 'Matches regex: ' : ''}${trigger.url}`}
                    </span>
                </ItemTitle>
                {checkUrlResult !== undefined && (
                    <Text
                        size="xs"
                        className={cn('flex items-center gap-1', {
                            'text-success-foreground': checkUrlResult === true,
                            'text-destructive-foreground': checkUrlResult === false,
                        })}
                        render={<span />}
                    >
                        {checkUrlResult ? (
                            <>
                                <IconCheck /> Matches
                            </>
                        ) : (
                            <>
                                <IconX /> No match
                            </>
                        )}
                    </Text>
                )}
            </ItemContent>
            <ItemActions>
                <Button onClick={() => onEdit(index)} tooltip="Edit" disabledReason={restrictedReason}>
                    <IconPencil />
                    Edit
                </Button>
                <Button
                    tooltip="Remove URL"
                    onClick={() => confirmRemoveUrl(index, onRemove)}
                    disabledReason={restrictedReason}
                >
                    <IconTrash />
                    Remove
                </Button>
            </ItemActions>
        </Item>
    )
}
