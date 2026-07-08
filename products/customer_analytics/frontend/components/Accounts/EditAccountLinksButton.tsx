import { useActions, useValues } from 'kea'

import { IconPencil } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonDropdown, LemonInput } from '@posthog/lemon-ui'

import { ACCOUNT_LINK_FIELDS, accountLinksLogic } from './accountLinksLogic'

export function EditAccountLinksButton({ accountId }: { accountId: string }): JSX.Element {
    const logic = accountLinksLogic({ accountId })
    const { editorOpen, formValues, savingLinks } = useValues(logic)
    const { openEditor, closeEditor, setFieldValue, saveLinks } = useActions(logic)

    return (
        <LemonDropdown
            closeOnClickInside={false}
            visible={editorOpen}
            onVisibilityChange={(visible) => {
                if (!visible) {
                    closeEditor()
                }
            }}
            showArrow
            overlay={
                <div className="flex flex-col gap-2 w-72">
                    {ACCOUNT_LINK_FIELDS.map((field) => (
                        <div key={field.key} className="flex flex-col gap-1">
                            <span className="text-xs font-semibold text-secondary">{field.label}</span>
                            <LemonInput
                                type="text"
                                size="small"
                                value={formValues[field.key]}
                                onChange={(value) => setFieldValue(field.key, value)}
                                placeholder={field.placeholder}
                                onPressEnter={saveLinks}
                            />
                        </div>
                    ))}
                    <LemonDivider className="my-1" />
                    <div className="flex flex-row gap-2 justify-end">
                        <LemonButton size="xsmall" type="secondary" onClick={closeEditor}>
                            Cancel
                        </LemonButton>
                        <LemonButton size="xsmall" type="primary" onClick={saveLinks} loading={savingLinks}>
                            Save
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <LemonButton
                size="xsmall"
                type="tertiary"
                icon={<IconPencil />}
                tooltip="Edit links"
                data-attr="edit-account-links"
                onClick={openEditor}
            />
        </LemonDropdown>
    )
}
