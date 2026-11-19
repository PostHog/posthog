import { useActions, useValues } from 'kea'
import { useContext, useState } from 'react'

import { IconEye, IconShuffle } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonDropdown, LemonTag } from '@posthog/lemon-ui'

import { CustomPersonForm } from './CustomPersonForm'
import { emailPreviewPersonLogic } from './emailPreviewPersonLogic'
import { EmailPreviewScopeContext } from './EmailPreviewScopeContext'
import { PersonSearch } from './PersonSearch'

/** Says whose values fill the preview, and lets the viewer swap who that is. */
export function EmailPreviewPersonBar({
    templates,
    unresolvedCount,
}: {
    templates: string[]
    unresolvedCount: number
}): JSX.Element {
    const scope = useContext(EmailPreviewScopeContext)
    const { previewPerson, personsLoading, personsFailed } = useValues(emailPreviewPersonLogic({ scope }))
    const { shufflePerson } = useActions(emailPreviewPersonLogic({ scope }))
    const [open, setOpen] = useState(false)

    return (
        <div className="ph-no-capture relative z-10 flex flex-wrap items-center gap-2 px-2 py-1 border-b bg-surface-secondary text-xs">
            <IconEye className="text-muted shrink-0" />
            <span className="text-muted">Previewing as</span>
            <LemonDropdown
                visible={open}
                onClickOutside={() => setOpen(false)}
                closeOnClickInside={false}
                overlay={
                    <div className="ph-no-capture flex flex-col gap-2 p-1 w-64">
                        {personsFailed ? (
                            <span className="text-muted text-xs">Couldn't load people. Fill in a custom person.</span>
                        ) : (
                            <PersonSearch onDone={() => setOpen(false)} />
                        )}
                        <LemonDivider className="my-0" />
                        <span className="font-semibold">Custom person</span>
                        <CustomPersonForm templates={templates} onDone={() => setOpen(false)} />
                    </div>
                }
            >
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    loading={personsLoading}
                    onClick={() => setOpen(!open)}
                    data-attr="email-preview-person-picker"
                >
                    {previewPerson?.displayName ?? (personsFailed ? 'Choose a person' : 'No one yet')}
                </LemonButton>
            </LemonDropdown>
            {!personsFailed && (
                <LemonButton
                    size="xsmall"
                    icon={<IconShuffle />}
                    tooltip="Random person"
                    onClick={shufflePerson}
                    data-attr="email-preview-random-person"
                />
            )}
            {unresolvedCount > 0 && (
                <LemonTag type="warning" size="small">
                    {unresolvedCount === 1 ? '1 field' : `${unresolvedCount} fields`} empty for this person
                </LemonTag>
            )}
        </div>
    )
}
